<#
.SYNOPSIS
    One-command deployment of the AI Report Generator to Azure Container Apps.

.DESCRIPTION
    1. Registers the required resource providers (first run on a fresh subscription).
    2. Creates the resource group and the container registry.
    3. Builds the Docker image IN THE CLOUD with `az acr build` (no local Docker needed).
    4. Deploys infra/main.bicep: Log Analytics, Container Apps env, Azure OpenAI
       (+ model deployments), the UI and API container apps, and a monthly budget.

.EXAMPLE
    .\infra\deploy.ps1                                  # full deploy with Azure OpenAI

.EXAMPLE
    .\infra\deploy.ps1 -UseAzureOpenAI:$false           # fallback: api.openai.com
                                                        # (key read from .env or prompted)
.EXAMPLE
    .\infra\deploy.ps1 -SkipBuild                       # redeploy infra only
#>
[CmdletBinding()]
param(
    [string]$Location = "swedencentral",
    [string]$ResourceGroup = "srg-rg",
    [string]$BaseName = "srg",
    [string]$AcrName = "",
    [string]$ImageTag = "latest",
    [bool]$UseAzureOpenAI = $true,
    [string]$OpenAIApiKey = "",
    [string]$BudgetEmail = "aron.sarosi13@gmail.com",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

# --- helper: read a KEY=value from the local .env (never committed) -----------------
function Get-DotenvValue([string]$key) {
    $envFile = Join-Path $repoRoot ".env"
    if (-not (Test-Path $envFile)) { return "" }
    $line = Get-Content $envFile | Where-Object { $_ -match "^\s*$key\s*=" } | Select-Object -First 1
    if ($null -eq $line) { return "" }
    return ($line -split "=", 2)[1].Trim()
}

# --- 0. subscription + deterministic ACR name ---------------------------------------
$subId = az account show --query id -o tsv
if (-not $subId) { throw "Not logged in. Run: az login" }
Write-Host "Subscription: $subId"

if (-not $AcrName) {
    # globally-unique but stable per subscription (lowercase alphanumeric only)
    $AcrName = "srgacr" + ($subId -replace "-", "").Substring(0, 10)
}
Write-Host "Registry:     $AcrName"

# --- 1. resource providers (no-ops when already registered) -------------------------
$providers = @("Microsoft.App", "Microsoft.ContainerRegistry",
               "Microsoft.OperationalInsights", "Microsoft.CognitiveServices")
foreach ($p in $providers) {
    $state = az provider show -n $p --query registrationState -o tsv
    if ($state -ne "Registered") {
        Write-Host "Registering provider $p (can take a few minutes)..."
        az provider register -n $p --wait
    }
}

# --- 2. resource group + registry ----------------------------------------------------
az group create -n $ResourceGroup -l $Location -o none
az acr create -n $AcrName -g $ResourceGroup --sku Basic --admin-enabled true -o none
Write-Host "Resource group + registry ready."

# --- 3. cloud image build ------------------------------------------------------------
if (-not $SkipBuild) {
    Write-Host "Building image in ACR (the LibreOffice layer makes the first build ~10-20 min)..."
    az acr build -r $AcrName -t "ai-report-generator:$ImageTag" $repoRoot
    if (-not $?) { throw "az acr build failed" }
}

# --- 4. secrets for the template -----------------------------------------------------
if (-not $UseAzureOpenAI -and -not $OpenAIApiKey) {
    $OpenAIApiKey = Get-DotenvValue "OPENAI_API_KEY"
    if (-not $OpenAIApiKey) {
        throw "UseAzureOpenAI is false but no OpenAI key found. Pass -OpenAIApiKey or set it in .env"
    }
}
$langfusePublic = Get-DotenvValue "LANGFUSE_PUBLIC_KEY"
$langfuseSecret = Get-DotenvValue "LANGFUSE_SECRET_KEY"
if ($langfusePublic) { Write-Host "Langfuse tracing: enabled" } else { Write-Host "Langfuse tracing: off (no keys in .env)" }

# --- 5. deploy the Bicep template ----------------------------------------------------
Write-Host "Deploying infra/main.bicep..."
$useAoai = if ($UseAzureOpenAI) { "true" } else { "false" }
az deployment group create `
    -g $ResourceGroup `
    -f (Join-Path $PSScriptRoot "main.bicep") `
    -p baseName=$BaseName `
       acrName=$AcrName `
       imageTag=$ImageTag `
       useAzureOpenAI=$useAoai `
       openaiApiKey=$OpenAIApiKey `
       langfusePublicKey=$langfusePublic `
       langfuseSecretKey=$langfuseSecret `
       budgetEmail=$BudgetEmail `
    --query "properties.outputs" -o json | Tee-Object -Variable outputsJson

if (-not $?) {
    Write-Host ""
    Write-Host "If the failure is an Azure OpenAI quota/offer error (common on free trial)," -ForegroundColor Yellow
    Write-Host "rerun with the OpenAI fallback:  .\infra\deploy.ps1 -SkipBuild -UseAzureOpenAI:`$false" -ForegroundColor Yellow
    throw "deployment failed"
}

$outputs = $outputsJson | ConvertFrom-Json
Write-Host ""
Write-Host "=== Deployed ===" -ForegroundColor Green
Write-Host ("UI:   https://" + $outputs.uiFqdn.value)
Write-Host ("API:  https://" + $outputs.apiFqdn.value + "  (docs at /docs)")
Write-Host ("AOAI: " + $outputs.aoaiEndpoint.value)
Write-Host ""
Write-Host "First request after idle cold-starts in 30-90s (scale-to-zero)."
