# Deploying to Azure (Container Apps + Azure OpenAI, via Bicep)

The whole stack is **infrastructure-as-code**: `infra/main.bicep` declares everything,
`infra/deploy.ps1` is the one-command wrapper. One Docker image serves two **Azure
Container Apps** (scale-to-zero → ~$0 when idle):

| App | What | Port |
|---|---|---|
| `srg-ui` | Streamlit demo (`APP_MODE=ui`) | 8501 |
| `srg-api` | FastAPI service: `/generate`, `/chat`, `/health` (`APP_MODE=api`) | 8000 |

Plus: Log Analytics, an Azure OpenAI account with `gpt-4o-mini` + `text-embedding-3-small`
deployments, and a monthly cost budget with email alerts. The image is built with local
Docker and pushed to ACR (ACR Tasks / `az acr build` is `TasksOperationsNotAllowed` on
free-trial subscriptions). Secrets (LLM keys, Langfuse) travel as Container Apps
**secrets**, never baked into the image.

## Deploy

```powershell
az login                  # once
.\infra\deploy.ps1        # full deploy (providers -> RG -> ACR -> image -> Bicep)
```

The script reads optional `LANGFUSE_*` keys from your local `.env` to enable tracing.
First image build takes ~10–20 min (the LibreOffice layer); rebuilds are minutes.

### Free-trial fallback: no Azure OpenAI quota

Free-trial subscriptions often have **zero Azure OpenAI quota**. If the deployment fails
on the `Microsoft.CognitiveServices` account or a model deployment, fall back to
api.openai.com — pure config, no code change (the `PROVIDER` switch in `src/config.py`):

```powershell
.\infra\deploy.ps1 -SkipBuild -UseAzureOpenAI:$false   # key read from .env or -OpenAIApiKey
```

Region note: pick a region with both Container Apps and AOAI model availability
(`swedencentral` and `eastus2` are safe bets); override with `-Location`.

## Redeploy after code changes

- **Automatic**: push to `main` → the `Deploy` GitHub Actions workflow builds a
  sha-tagged image in ACR and updates both apps (see `.github/workflows/deploy.yml`).
- **Manual**: `.\infra\deploy.ps1` again (rebuilds `latest` and re-applies the Bicep).

## Verification checklist

```powershell
# 1. API (first hit after idle cold-starts in 30-90s)
curl.exe --max-time 180 https://<api-fqdn>/health          # {"status":"ok"}
curl.exe -X POST https://<api-fqdn>/generate -F "intent=Monthly sales review" `
         -o report.pptx --max-time 300                      # opens as a valid deck
curl.exe -X POST https://<api-fqdn>/chat -F "question=top region by revenue last month"

# 2. UI: open https://<ui-fqdn>, click "Use sample data", generate a report, download PDF
# 3. Langfuse: cloud.langfuse.com shows the analyze->plan->write->verify trace per report
# 4. Evals (local, costs API money): python eval/run_all.py  -> eval/REPORT.md
# 5. CI/CD: push to main -> Deploy workflow green -> new revision:
az containerapp revision list -n srg-api -g srg-rg -o table
```

## Cost guardrails (trial credits)

- **Scale-to-zero** (`minReplicas: 0`, in Bicep) — no compute cost while idle; the
  trade-off is a 30–90 s cold start on the first request. Warm it up before live demos,
  or temporarily set `minReplicas: 1`.
- **Budget**: `Microsoft.Consumption/budgets` ($25/month, email at 80% and 100%) is part
  of the template. If your subscription offer rejects the budgets API, add it manually:
  portal → Cost Management → Budgets.
- **ACR Basic** includes 10 GB; sha-tagged images add up. Clean old tags occasionally:

```powershell
az acr repository show-tags -n <acr> --repository ai-report-generator -o table
az acr repository untag -n <acr> --image ai-report-generator:<old-sha>
```

## Teardown

```powershell
az group delete -n srg-rg --yes --no-wait
```

The repo still documents the full deployment (Bicep + workflows) after teardown.

## CI/CD wiring (GitHub OIDC — one-time manual setup)

The `Deploy` workflow logs into Azure with **OIDC federated credentials** (no stored
service-principal secret):

1. **Entra ID → App registrations → New registration** — name `gh-ai-report-generator`,
   defaults, Register. Note the **Application (client) ID** and **Directory (tenant) ID**.
2. In the registration → **Certificates & secrets → Federated credentials → Add** →
   scenario *GitHub Actions deploying Azure resources* → org `AronSarosi`, repo
   `ai-report-generator`, entity **Branch**, branch `main`.
3. **Resource group `srg-rg` → Access control (IAM) → Add role assignment** →
   **Contributor** → the `gh-ai-report-generator` app. (RG-scoped: the workflow only
   needs `az acr build` + `az containerapp update`.)
4. GitHub repo → **Settings → Secrets and variables → Actions** → add
   `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`.
5. Validate: Actions → Deploy → **Run workflow**.

## Appendix: manual CLI walkthrough (what the script automates)

<details>
<summary>Step-by-step az commands (the original Phase B walkthrough)</summary>

```powershell
$RG = "srg-rg"; $LOC = "swedencentral"; $ACR = "<unique-acr-name>"; $APP = "ai-report-generator"

az group create -n $RG -l $LOC
az acr create -n $ACR -g $RG --sku Basic --admin-enabled true
az acr build -r $ACR -t "$APP:latest" .

az extension add --name containerapp --upgrade
az containerapp env create -n srg-env -g $RG -l $LOC

# ... then one `az containerapp create` per app with --env-vars APP_MODE=ui|api,
# PROVIDER/AZURE_OPENAI_* (or OPENAI_API_KEY) passed via --secrets + secretref.
# infra/main.bicep is the source of truth for the full wiring.
```

</details>
