// Azure infrastructure for the AI Report Generator.
//
// One deployment creates:
//   - Log Analytics workspace + Container Apps environment (Consumption, scale-to-zero)
//   - Azure OpenAI (gpt-4o-mini + text-embedding-3-small) when useAzureOpenAI = true;
//     otherwise the apps run against api.openai.com with the key passed as a secret
//   - Two Container Apps from ONE image: the Streamlit UI and the FastAPI service
//     (the image's APP_MODE env var selects the server, see docker/entrypoint.sh)
//   - A monthly cost budget with email alerts
//
// The container registry is created by infra/deploy.ps1 BEFORE this template runs,
// because the image must already be in ACR when the container apps are created.
// ACR admin credentials keep this a single self-contained template; the production
// upgrade is a user-assigned managed identity with AcrPull (needs a two-step deploy).

param location string = resourceGroup().location
param baseName string = 'srg'
param acrName string
param imageTag string = 'latest'

@description('Deploy Azure OpenAI and point the apps at it. Set false on subscriptions without AOAI quota (free trial) to use api.openai.com instead.')
param useAzureOpenAI bool = true

@secure()
@description('OpenAI API key — only used when useAzureOpenAI = false.')
param openaiApiKey string = ''

@secure()
param langfusePublicKey string = ''
@secure()
param langfuseSecretKey string = ''
param langfuseHost string = 'https://cloud.langfuse.com'

param budgetAmount int = 25
param budgetEmail string
param budgetStartDate string = utcNow('yyyy-MM-01')

var image = '${acr.properties.loginServer}/ai-report-generator:${imageTag}'
var chatDeployment = 'gpt-4o-mini'
var embedDeployment = 'text-embedding-3-small'
var langfuseEnabled = !empty(langfusePublicKey) && !empty(langfuseSecretKey)

// --------------------------------------------------------------------------- //
// Observability + Container Apps environment
// --------------------------------------------------------------------------- //
resource logs 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: '${baseName}-logs'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${baseName}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

// --------------------------------------------------------------------------- //
// Azure OpenAI (conditional)
// --------------------------------------------------------------------------- //
resource aoai 'Microsoft.CognitiveServices/accounts@2024-10-01' = if (useAzureOpenAI) {
  name: '${baseName}-aoai-${uniqueString(resourceGroup().id)}'
  location: location
  kind: 'OpenAI'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: '${baseName}-aoai-${uniqueString(resourceGroup().id)}'
    publicNetworkAccess: 'Enabled'
  }
}

resource chatModel 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = if (useAzureOpenAI) {
  parent: aoai
  name: chatDeployment
  sku: { name: 'GlobalStandard', capacity: 8 }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-4o-mini', version: '2024-07-18' }
  }
}

resource embedModel 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = if (useAzureOpenAI) {
  parent: aoai
  name: embedDeployment
  sku: { name: 'Standard', capacity: 50 }
  properties: {
    model: { format: 'OpenAI', name: 'text-embedding-3-small', version: '1' }
  }
  dependsOn: [chatModel] // AOAI allows only one deployment operation at a time
}

// --------------------------------------------------------------------------- //
// Registry (pre-created by deploy.ps1) + shared app wiring
// --------------------------------------------------------------------------- //
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
}

var registries = [
  {
    server: acr.properties.loginServer
    username: acr.listCredentials().username
    passwordSecretRef: 'acr-password'
  }
]

var secrets = concat(
  [
    { name: 'acr-password', value: acr.listCredentials().passwords[0].value }
    {
      name: 'llm-key'
      // the ternaries below are lazily evaluated by ARM, so aoai is only touched
      // when useAzureOpenAI is true (the ! asserts that to the type checker)
      value: useAzureOpenAI ? aoai!.listKeys().key1 : openaiApiKey
    }
  ],
  langfuseEnabled ? [{ name: 'langfuse-secret-key', value: langfuseSecretKey }] : []
)

var providerEnv = useAzureOpenAI ? [
  { name: 'PROVIDER', value: 'azure' }
  { name: 'AZURE_OPENAI_ENDPOINT', value: aoai!.properties.endpoint }
  { name: 'AZURE_OPENAI_API_VERSION', value: '2024-10-21' }
  { name: 'AZURE_OPENAI_CHAT_DEPLOYMENT', value: chatDeployment }
  { name: 'AZURE_OPENAI_EMBED_DEPLOYMENT', value: embedDeployment }
  { name: 'AZURE_OPENAI_API_KEY', secretRef: 'llm-key' }
] : [
  { name: 'PROVIDER', value: 'openai' }
  { name: 'OPENAI_API_KEY', secretRef: 'llm-key' }
]

var langfuseEnv = langfuseEnabled ? [
  { name: 'LANGFUSE_PUBLIC_KEY', value: langfusePublicKey }
  { name: 'LANGFUSE_SECRET_KEY', secretRef: 'langfuse-secret-key' }
  { name: 'LANGFUSE_HOST', value: langfuseHost }
] : []

var sharedEnv = concat(providerEnv, langfuseEnv)

// --------------------------------------------------------------------------- //
// The two apps: same image, different APP_MODE
// --------------------------------------------------------------------------- //
resource ui 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${baseName}-ui'
  location: location
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8501
        transport: 'auto' // Streamlit needs websockets
        stickySessions: { affinity: 'sticky' } // session state lives in the replica
      }
      registries: registries
      secrets: secrets
    }
    template: {
      containers: [
        {
          name: 'ui'
          image: image
          resources: { cpu: json('1.0'), memory: '2Gi' } // LibreOffice PDF render headroom
          env: concat(sharedEnv, [
            { name: 'APP_MODE', value: 'ui' }
            { name: 'PORT', value: '8501' }
          ])
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 1 } // scale-to-zero: ~free when idle
    }
  }
}

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${baseName}-api'
  location: location
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
      }
      registries: registries
      secrets: secrets
    }
    template: {
      containers: [
        {
          name: 'api'
          image: image
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: concat(sharedEnv, [
            { name: 'APP_MODE', value: 'api' }
            { name: 'PORT', value: '8000' }
          ])
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/health', port: 8000 }
              initialDelaySeconds: 15
              periodSeconds: 30
            }
          ]
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
}

// --------------------------------------------------------------------------- //
// Cost guardrail: monthly budget with email alerts at 80% and 100%
// --------------------------------------------------------------------------- //
resource budget 'Microsoft.Consumption/budgets@2023-11-01' = {
  name: '${baseName}-budget'
  properties: {
    category: 'Cost'
    amount: budgetAmount
    timeGrain: 'Monthly'
    timePeriod: { startDate: budgetStartDate }
    notifications: {
      actual80: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 80
        contactEmails: [budgetEmail]
      }
      actual100: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 100
        contactEmails: [budgetEmail]
      }
    }
  }
}

output uiFqdn string = ui.properties.configuration.ingress.fqdn
output apiFqdn string = api.properties.configuration.ingress.fqdn
output acrLoginServer string = acr.properties.loginServer
output aoaiEndpoint string = useAzureOpenAI ? aoai!.properties.endpoint : '(using api.openai.com)'
