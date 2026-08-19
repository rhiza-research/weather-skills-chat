# weather-skills-chat Helm chart

Deploys the Weather Skills chat app (Open WebUI fork) with:

- One replica, SQLite on a PVC by default
- Whisper / embedding weights left in the image (not copied onto the PVC)
- Optional GKE GCS FUSE mount for skill artifacts
- Secrets supplied by you as a pre-created Kubernetes Secret

This is not the upstream Open WebUI chart. It does not install Ollama, Pipelines, Redis, or Postgres.

## Install

The chart **requires** `secretName`: the name of a Kubernetes Secret you create externally. That Secret must contain `WEBUI_SECRET_KEY`. Helm does not create or populate the Secret.

```bash
helm install weather-skills-chat ./charts/weather-skills-chat \
  --set secretName=weather-skills-chat-secrets
```

Port-forward:

```bash
kubectl port-forward svc/weather-skills-chat-weather-skills-chat 3000:80
```

Image default is `ghcr.io/rhiza-research/weather-skills-chat:main`. If the GHCR package is private, set `imagePullSecrets`.

## Secrets

Create the Kubernetes Secret with your own tooling (e.g. `kubectl`, a CI job, or `gcloud` + `kubectl`). The chart only references it by name.

Minimum:

```bash
kubectl create secret generic weather-skills-chat-secrets \
  --from-literal=WEBUI_SECRET_KEY="$WEBUI_SECRET_KEY"
```

Example using Google Secret Manager as the source of truth:

```bash
kubectl create secret generic weather-skills-chat-secrets \
  --from-literal=WEBUI_SECRET_KEY="$(gcloud secrets versions access latest --secret=weather-skills-chat-webui-secret-key)"
```

Optional keys on the **same** Secret:

| Key | Used when |
|---|---|
| `WEBUI_SECRET_KEY` | Always (required) |
| `DATABASE_URL` | Postgres; omit for SQLite on the PVC. Password belongs in this URL, not in values.yaml |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | `langfuse.enabled: true` (required then; optional otherwise) |
| `OPENAI_API_KEY` | OpenAI-compatible API key (e.g. Anthropic); pair with `openai.apiBaseUrl` |
| `BOOTSTRAP_ADMIN_PASSWORD` | Initial admin password when `bootstrapAdmin.enabled` is true |
| `GOOGLE_CLIENT_SECRET` | Google OAuth when `oauth.google.clientId` is set |
| `MICROSOFT_CLIENT_SECRET` | Microsoft OAuth when `oauth.microsoft.clientId` is set |
| `GITHUB_CLIENT_SECRET` | GitHub OAuth when `oauth.github.clientId` is set |
| `OAUTH_CLIENT_SECRET` | Generic OIDC when `oauth.oidc.clientId` is set |
| `EMAIL_TOOL_SMTP_PASSWORD` | Built-in `send_email` SMTP password |

If your Secret uses different field names, override `secretKeys` in values.yaml.

## Persistence vs Postgres

Default: `DATABASE_URL` unset → SQLite at `/app/backend/data/webui.db` on a 20Gi RWO PVC.

### Pod restart vs Helm uninstall

- **Pod restart / crash / rollout:** the PVC is **not** deleted. Kubernetes detaches the volume from the old pod and reattaches it to the new one. Your SQLite DB, skills, and artifacts stay on the disk.
- **Helm uninstall:** if the chart created the PVC, Helm **deletes the PVC by default** (which can delete the underlying dynamically provisioned disk on GKE). Set `persistence.keep: true` to add `helm.sh/resource-policy: keep` so the PVC survives uninstall.
- **Chart upgrade:** the PVC is reused; data is preserved.

### Pre-provisioned GCE disk (recommended for backup policy)

Create a GCE persistent disk with your backup/snapshot policy, then pass its **disk name** (`pdName`) as `volumeName`. The chart creates a static PV and PVC that bind to that disk:

```yaml
persistence:
  volumeName: weather-skills-data-disk   # GCE persistent disk name
  size: 20Gi                             # must be <= disk capacity
  reclaimPolicy: Retain                  # disk survives PV/PVC deletion
  keep: true                             # PV/PVC survive helm uninstall
```

```bash
helm install weather-skills-chat ./charts/weather-skills-chat \
  --set secretName=weather-skills-chat-secrets \
  --set persistence.volumeName=weather-skills-data-disk
```

The Kubernetes PV is named `{release}-weather-skills-chat-pv`; the PVC is `{release}-weather-skills-chat`. The disk must exist in the **same zone** as the node that schedules the pod (standard RWO GCE PD).

### Existing PVC only

If you already have a PVC (and optionally PV), set `persistence.existingClaim` — the chart mounts it and creates nothing.

```yaml
persistence:
  existingClaim: weather-skills-data
```

### Dynamic provisioning (default)

When both `volumeName` and `existingClaim` are empty, the chart creates a PVC and relies on `storageClass` for dynamic provisioning.

Keep `replicaCount: 1` with SQLite. For Postgres, add `DATABASE_URL` to the Secret (including password). Do not put passwords in values.yaml.

The PVC is mounted **only** at `DATA_DIR` (`/app/backend/data`): SQLite, skills packs, uv-cache, uploads, Chroma, runtime caches (speech/images). There is no copy-app-data init container.

## Whisper / embeddings (image, not PVC)

Baked model weights live at `/app/backend/cache` inside the image:

| Env | Path |
|---|---|
| `MODEL_CACHE_DIR` | `/app/backend/cache` |
| `WHISPER_MODEL_DIR` | `/app/backend/cache/whisper/models` |
| `HF_HOME` / `TRANSFORMERS_CACHE` / `SENTENCE_TRANSFORMERS_HOME` | `/app/backend/cache/embedding/models` |
| `TIKTOKEN_CACHE_DIR` | `/app/backend/cache/tiktoken` |

A PVC on `/app/backend/data` does not hide these files.

## Skill artifacts and GCS FUSE

By default `ARTIFACTS_DIR` is `{DATA_DIR}/artifacts` on the data PVC (`chat_sandbox()` → `{ARTIFACTS_DIR}/{chat_id}`).

To put artifacts on a GCS bucket, use a **separate** CSI mount (not nested on the data PVC). This does **not** set `STORAGE_PROVIDER=gcs` (that Open WebUI path is only chat file uploads).

Cluster prerequisites:

1. GKE cluster with the [GCS FUSE CSI driver](https://cloud.google.com/kubernetes-engine/docs/how-to/persistent-volumes/cloud-storage-fuse-csi-driver) enabled.
2. [Workload Identity](https://cloud.google.com/kubernetes-engine/docs/how-to/workload-identity) enabled.
3. A Google service account (GSA) with `roles/storage.objectAdmin` (or tighter) on the bucket.
4. Bind the GSA to this chart’s Kubernetes service account.

```bash
gcloud iam service-accounts add-iam-policy-binding GSA_NAME@PROJECT.iam.gserviceaccount.com \
  --role roles/iam.workloadIdentityUser \
  --member "serviceAccount:PROJECT.svc.id.goog[NAMESPACE/KSA_NAME]"
```

`KSA_NAME` defaults to `{release}-weather-skills-chat`.

values:

```yaml
serviceAccount:
  create: true
  annotations:
    iam.gke.io/gcp-service-account: GSA_NAME@PROJECT.iam.gserviceaccount.com

sandbox:
  gcs:
    enabled: true
    bucket: my-artifacts-bucket
    mountPath: /mnt/gcs-artifacts
```

The chart sets `ARTIFACTS_DIR=/mnt/gcs-artifacts` and annotates the pod with `gke-gcsfuse/volumes: "true"`.

## OpenAI-compatible API (Anthropic, OpenAI, …)

```yaml
openai:
  enabled: true
  apiBaseUrl: https://api.anthropic.com/v1
```

Put the matching API key in the Secret as `OPENAI_API_KEY`.

## Bootstrap admin

On a fresh install, create the first admin from env vars (does not disable signup):

```yaml
bootstrapAdmin:
  enabled: true
  email: admin@admin.local
  name: admin
```

Add `BOOTSTRAP_ADMIN_PASSWORD` to the Secret. New signups get `webui.defaultUserRole` (`pending` by default) until an admin approves them.

## Langfuse

```yaml
secretName: weather-skills-chat-secrets

langfuse:
  enabled: true
  host: https://us.cloud.langfuse.com
```

Add `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` to the same Secret. Unused env vars are harmless if tracing is disabled.

## OAuth / OIDC (Terraform)

All Open WebUI OAuth env vars are Helm values except **client secrets**, which stay on the same Kubernetes Secret as `WEBUI_SECRET_KEY`. A provider is enabled only when both its client ID (values) and client secret (Secret) are present.

Redirect URIs: leave empty unless the public URL differs from the request host. Google Cloud Console must allow `{origin}/oauth/google/callback` (Microsoft `/oauth/microsoft/callback`, GitHub `/oauth/github/callback`, generic OIDC `/oauth/oidc/callback`).

A setting **in the environment pins that key** (env wins over SQLite, including after UI saves). Unset keys still persist from the admin UI. Leave a Helm value `null` / empty to omit the env var and keep UI control; set it only when Terraform should own that key.

### Google (merge admin-created users by email)

```yaml
oauth:
  enableSignup: false          # pin: unknown Google accounts cannot self-register
  mergeAccountsByEmail: true   # pin: admin-added email matches Google email → login
  allowedDomains:
    - rhiza.io
  google:
    clientId: "....apps.googleusercontent.com"
    # redirectUri: https://chat.example.com/oauth/google/callback
```

Add `GOOGLE_CLIENT_SECRET` to the Secret.

### Generic OIDC

```yaml
oauth:
  enableSignup: true
  mergeAccountsByEmail: true
  allowedDomains: [rhiza.io]
  oidc:
    clientId: "..."
    providerUrl: https://accounts.google.com/.well-known/openid-configuration
    providerName: Google
```

Secret key: `OAUTH_CLIENT_SECRET`. Microsoft and GitHub follow the same pattern (`oauth.microsoft.*` + `MICROSOFT_CLIENT_SECRET`, `oauth.github.*` + `GITHUB_CLIENT_SECRET`). Microsoft also needs `oauth.microsoft.tenantId`.

### Helm values → env

| values.yaml | Env |
|---|---|
| `oauth.enableSignup` | `ENABLE_OAUTH_SIGNUP` |
| `oauth.mergeAccountsByEmail` | `OAUTH_MERGE_ACCOUNTS_BY_EMAIL` |
| `oauth.enableRoleManagement` | `ENABLE_OAUTH_ROLE_MANAGEMENT` |
| `oauth.enableGroupManagement` | `ENABLE_OAUTH_GROUP_MANAGEMENT` |
| `oauth.allowedDomains` | `OAUTH_ALLOWED_DOMAINS` (comma-joined) |
| `oauth.allowedRoles` / `oauth.adminRoles` | `OAUTH_ALLOWED_ROLES` / `OAUTH_ADMIN_ROLES` |
| `oauth.usernameClaim` / `pictureClaim` / `emailClaim` / `groupsClaim` / `rolesClaim` | `OAUTH_*_CLAIM` |
| `oauth.google.clientId` / `scope` / `redirectUri` | `GOOGLE_CLIENT_ID` / `GOOGLE_OAUTH_SCOPE` / `GOOGLE_REDIRECT_URI` |
| `oauth.microsoft.clientId` / `tenantId` / `scope` / `redirectUri` | `MICROSOFT_CLIENT_*` / `MICROSOFT_OAUTH_SCOPE` / `MICROSOFT_REDIRECT_URI` |
| `oauth.github.clientId` / `scope` / `redirectUri` | `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SCOPE` / `GITHUB_CLIENT_REDIRECT_URI` |
| `oauth.oidc.clientId` / `providerUrl` / `redirectUri` / `scopes` / `providerName` / `codeChallengeMethod` | `OAUTH_CLIENT_ID` / `OPENID_PROVIDER_URL` / `OPENID_REDIRECT_URI` / `OAUTH_SCOPES` / `OAUTH_PROVIDER_NAME` / `OAUTH_CODE_CHALLENGE_METHOD` |
| `emailTool.smtpHost` / `smtpPort` / `smtpUsername` / `smtpUseTls` / `fromEmail` | `EMAIL_TOOL_SMTP_HOST` / `EMAIL_TOOL_SMTP_PORT` / `EMAIL_TOOL_SMTP_USERNAME` / `EMAIL_TOOL_SMTP_USE_TLS` / `EMAIL_TOOL_FROM_EMAIL` |

Empty strings, empty lists, and `null` omit the env var (UI persist / app default). A boolean `true`/`false` pins that flag.

### Terraform (`helm_release`)

```hcl
resource "helm_release" "weather_skills_chat" {
  name       = "weather-skills-chat"
  chart      = "./charts/weather-skills-chat"
  namespace  = var.namespace

  values = [
    yamlencode({
      secretName = kubernetes_secret.weather_skills.metadata[0].name
      oauth = {
        enableSignup         = false
        mergeAccountsByEmail = true
        allowedDomains       = ["rhiza.io"]
        google = {
          clientId = var.google_oauth_client_id
        }
      }
    })
  ]
}
```

Put `GOOGLE_CLIENT_SECRET` (and other client secrets) on `kubernetes_secret.weather_skills`, sourced from Google Secret Manager. Do not put secrets in Helm values.

## Ollama

`ENABLE_OLLAMA_API=false` by default. Point the UI at OpenAI-compatible APIs (`openai.apiBaseUrl` + `OPENAI_API_KEY` in the Secret) instead.
