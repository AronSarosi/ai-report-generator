# Deploying to Azure (Container Apps + Azure OpenAI)

This deploys the Streamlit app to **Azure Container Apps** (scale-to-zero, so it costs
~$0 when idle) running on **Azure OpenAI**. The image is built **in the cloud** with
`az acr build`, so you do not even need Docker installed locally.

Secrets (API keys) are passed as Container Apps **secrets** and never baked into the image.

## 0. Prerequisites

- An Azure subscription (the free trial is fine).
- The Azure CLI: `winget install Microsoft.AzureCLI`, then `az login`.
- An Azure OpenAI resource with `gpt-4o-mini` and `text-embedding-3-small` deployed
  (see the main setup checklist). You will need its **endpoint** and a **key**.

## 1. Set variables (PowerShell)

```powershell
$RG       = "srg-rg"                       # resource group
$LOC      = "swedencentral"                # a region with Container Apps + your AOAI
$ACR      = "srgacr$(Get-Random -Max 9999)"   # registry name (globally unique, lowercase)
$APP      = "ai-report-generator"
$ENVNAME  = "srg-env"

# From your Azure OpenAI resource (fill these in):
$AOAI_ENDPOINT   = "https://<your-resource>.openai.azure.com/"
$AOAI_KEY        = "<your-azure-openai-key>"
$AOAI_APIVER     = "2024-10-21"
$AOAI_CHAT       = "gpt-4o-mini"
$AOAI_EMBED      = "text-embedding-3-small"
```

## 2. Resource group + registry, then build the image in the cloud

```powershell
az group create -n $RG -l $LOC

az acr create -n $ACR -g $RG --sku Basic --admin-enabled true

# Builds the Dockerfile in ACR (no local Docker needed) and pushes it:
az acr build -r $ACR -t "$APP:latest" .
```

## 3. Create the Container Apps environment + the app

```powershell
az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights

az containerapp env create -n $ENVNAME -g $RG -l $LOC

$ACR_SERVER = az acr show -n $ACR --query loginServer -o tsv
$ACR_USER   = az acr credential show -n $ACR --query username -o tsv
$ACR_PASS   = az acr credential show -n $ACR --query "passwords[0].value" -o tsv

az containerapp create `
  -n $APP -g $RG --environment $ENVNAME `
  --image "$ACR_SERVER/$APP:latest" `
  --registry-server $ACR_SERVER --registry-username $ACR_USER --registry-password $ACR_PASS `
  --target-port 8501 --ingress external `
  --min-replicas 0 --max-replicas 2 `
  --secrets aoai-key=$AOAI_KEY `
  --env-vars `
     PROVIDER=azure `
     AZURE_OPENAI_ENDPOINT=$AOAI_ENDPOINT `
     AZURE_OPENAI_API_KEY=secretref:aoai-key `
     AZURE_OPENAI_API_VERSION=$AOAI_APIVER `
     AZURE_OPENAI_CHAT_DEPLOYMENT=$AOAI_CHAT `
     AZURE_OPENAI_EMBED_DEPLOYMENT=$AOAI_EMBED
```

`--min-replicas 0` is the key cost lever: when no one is using the app, Azure shuts every
replica down and you pay nothing for compute. The first request after idle takes a few
seconds to cold-start. `AZURE_OPENAI_API_KEY=secretref:aoai-key` injects the key from the
secret, so it never appears in the image or in `az` history as plain text in the container.

## 4. Get the public URL

```powershell
az containerapp show -n $APP -g $RG --query "properties.configuration.ingress.fqdn" -o tsv
# Open https://<that-fqdn>  ->  the app should load (after a short cold start).
```

## 5. Redeploy after code changes

```powershell
az acr build -r $ACR -t "$APP:latest" .
az containerapp update -n $APP -g $RG --image "$ACR_SERVER/$APP:latest"
```

## 6. Cost control + teardown

- Scale-to-zero (`--min-replicas 0`) + `gpt-4o-mini` keeps idle cost near zero.
- Set an OpenAI/Azure budget alert as a backstop.
- When you are done demoing, delete everything in one command:

```powershell
az group delete -n $RG --yes --no-wait
```

The Azure resources are gone, but this repo still documents the full deployment — proof of
the Azure / Docker / Container Apps skills even after teardown.

## Optional: run the FastAPI surface instead of the UI

The same engine is exposed as an API in `app/main.py`. To deploy that instead of the UI,
change the Dockerfile `CMD` to:

```dockerfile
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
```

and set `--target-port` to match. Locally: `uvicorn app.main:app --reload` then open `/docs`.
