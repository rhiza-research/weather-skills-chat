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
| `OPENAI_API_KEY` | Optional; can also be set in the UI (stored in SQLite) |

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

## Langfuse

```yaml
secretName: weather-skills-chat-secrets

langfuse:
  enabled: true
  host: https://us.cloud.langfuse.com
```

Add `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` to the same Secret. Unused env vars are harmless if tracing is disabled.

## Ollama

`ENABLE_OLLAMA_API=false` by default. Point the UI at OpenAI-compatible APIs (`openai.apiBaseUrl` + `OPENAI_API_KEY` in the Secret) instead.
