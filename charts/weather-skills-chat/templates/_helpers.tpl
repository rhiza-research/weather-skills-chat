{{/*
Expand the name of the chart.
*/}}
{{- define "weather-skills-chat.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "weather-skills-chat.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Chart label.
*/}}
{{- define "weather-skills-chat.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "weather-skills-chat.labels" -}}
helm.sh/chart: {{ include "weather-skills-chat.chart" . }}
{{ include "weather-skills-chat.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "weather-skills-chat.selectorLabels" -}}
app.kubernetes.io/name: {{ include "weather-skills-chat.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "weather-skills-chat.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "weather-skills-chat.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "weather-skills-chat.image" -}}
{{- $tag := .Values.image.tag | default .Chart.AppVersion }}
{{- printf "%s:%s" .Values.image.repository $tag }}
{{- end }}

{{- define "weather-skills-chat.pvcName" -}}
{{- if .Values.persistence.existingClaim }}
{{- .Values.persistence.existingClaim }}
{{- else }}
{{- include "weather-skills-chat.fullname" . }}
{{- end }}
{{- end }}

{{- define "weather-skills-chat.pvName" -}}
{{- printf "%s-pv" (include "weather-skills-chat.fullname" .) }}
{{- end }}

{{/*
Kubernetes Secret created out-of-band (must contain WEBUI_SECRET_KEY).
*/}}
{{- define "weather-skills-chat.secretName" -}}
{{- required "secretName is required: create a Kubernetes Secret externally and set secretName to its name." .Values.secretName }}
{{- end }}

{{- define "weather-skills-chat.artifactsDir" -}}
{{- if .Values.sandbox.gcs.enabled }}
{{- .Values.sandbox.gcs.mountPath }}
{{- else }}
{{- .Values.sandbox.artifactsDir }}
{{- end }}
{{- end }}

{{/*
Join a Helm list or pass through a comma-separated string (Terraform --set friendly).
*/}}
{{- define "weather-skills-chat.csv" -}}
{{- if kindIs "slice" . -}}
{{- join "," . -}}
{{- else -}}
{{- . -}}
{{- end -}}
{{- end }}

{{/*
Emit an env var only when the Helm value is not null. false is a real pin.
*/}}
{{- define "weather-skills-chat.optionalEnv" -}}
{{- if ne (toJson .value) "null" }}
- name: {{ .name }}
  value: {{ .value | quote }}
{{- end }}
{{- end }}

{{/*
OAuth / OIDC env. Only emit values you want to pin; unset keys stay UI/DB-managed.
Client secrets come from the same external Secret as WEBUI_SECRET_KEY.
*/}}
{{- define "weather-skills-chat.oauthEnv" -}}
{{- include "weather-skills-chat.optionalEnv" (dict "name" "ENABLE_OAUTH_SIGNUP" "value" .Values.oauth.enableSignup) }}
{{- include "weather-skills-chat.optionalEnv" (dict "name" "OAUTH_MERGE_ACCOUNTS_BY_EMAIL" "value" .Values.oauth.mergeAccountsByEmail) }}
{{- include "weather-skills-chat.optionalEnv" (dict "name" "ENABLE_OAUTH_ROLE_MANAGEMENT" "value" .Values.oauth.enableRoleManagement) }}
{{- include "weather-skills-chat.optionalEnv" (dict "name" "ENABLE_OAUTH_GROUP_MANAGEMENT" "value" .Values.oauth.enableGroupManagement) }}
{{- with .Values.oauth.allowedDomains }}
- name: OAUTH_ALLOWED_DOMAINS
  value: {{ include "weather-skills-chat.csv" . | quote }}
{{- end }}
{{- with .Values.oauth.allowedRoles }}
- name: OAUTH_ALLOWED_ROLES
  value: {{ include "weather-skills-chat.csv" . | quote }}
{{- end }}
{{- with .Values.oauth.adminRoles }}
- name: OAUTH_ADMIN_ROLES
  value: {{ include "weather-skills-chat.csv" . | quote }}
{{- end }}
{{- with .Values.oauth.usernameClaim }}
- name: OAUTH_USERNAME_CLAIM
  value: {{ . | quote }}
{{- end }}
{{- with .Values.oauth.pictureClaim }}
- name: OAUTH_PICTURE_CLAIM
  value: {{ . | quote }}
{{- end }}
{{- with .Values.oauth.emailClaim }}
- name: OAUTH_EMAIL_CLAIM
  value: {{ . | quote }}
{{- end }}
{{- with .Values.oauth.groupsClaim }}
- name: OAUTH_GROUPS_CLAIM
  value: {{ . | quote }}
{{- end }}
{{- with .Values.oauth.rolesClaim }}
- name: OAUTH_ROLES_CLAIM
  value: {{ . | quote }}
{{- end }}
{{- with .Values.oauth.google.clientId }}
- name: GOOGLE_CLIENT_ID
  value: {{ . | quote }}
- name: GOOGLE_CLIENT_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ include "weather-skills-chat.secretName" $ }}
      key: {{ $.Values.secretKeys.googleClientSecret | quote }}
      optional: true
{{- end }}
{{- with .Values.oauth.google.scope }}
- name: GOOGLE_OAUTH_SCOPE
  value: {{ . | quote }}
{{- end }}
{{- with .Values.oauth.google.redirectUri }}
- name: GOOGLE_REDIRECT_URI
  value: {{ . | quote }}
{{- end }}
{{- with .Values.oauth.microsoft.clientId }}
- name: MICROSOFT_CLIENT_ID
  value: {{ . | quote }}
- name: MICROSOFT_CLIENT_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ include "weather-skills-chat.secretName" $ }}
      key: {{ $.Values.secretKeys.microsoftClientSecret | quote }}
      optional: true
{{- end }}
{{- with .Values.oauth.microsoft.tenantId }}
- name: MICROSOFT_CLIENT_TENANT_ID
  value: {{ . | quote }}
{{- end }}
{{- with .Values.oauth.microsoft.scope }}
- name: MICROSOFT_OAUTH_SCOPE
  value: {{ . | quote }}
{{- end }}
{{- with .Values.oauth.microsoft.redirectUri }}
- name: MICROSOFT_REDIRECT_URI
  value: {{ . | quote }}
{{- end }}
{{- with .Values.oauth.github.clientId }}
- name: GITHUB_CLIENT_ID
  value: {{ . | quote }}
- name: GITHUB_CLIENT_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ include "weather-skills-chat.secretName" $ }}
      key: {{ $.Values.secretKeys.githubClientSecret | quote }}
      optional: true
{{- end }}
{{- with .Values.oauth.github.scope }}
- name: GITHUB_CLIENT_SCOPE
  value: {{ . | quote }}
{{- end }}
{{- with .Values.oauth.github.redirectUri }}
- name: GITHUB_CLIENT_REDIRECT_URI
  value: {{ . | quote }}
{{- end }}
{{- with .Values.oauth.oidc.clientId }}
- name: OAUTH_CLIENT_ID
  value: {{ . | quote }}
- name: OAUTH_CLIENT_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ include "weather-skills-chat.secretName" $ }}
      key: {{ $.Values.secretKeys.oidcClientSecret | quote }}
      optional: true
{{- end }}
{{- with .Values.oauth.oidc.providerUrl }}
- name: OPENID_PROVIDER_URL
  value: {{ . | quote }}
{{- end }}
{{- with .Values.oauth.oidc.redirectUri }}
- name: OPENID_REDIRECT_URI
  value: {{ . | quote }}
{{- end }}
{{- with .Values.oauth.oidc.scopes }}
- name: OAUTH_SCOPES
  value: {{ . | quote }}
{{- end }}
{{- with .Values.oauth.oidc.providerName }}
- name: OAUTH_PROVIDER_NAME
  value: {{ . | quote }}
{{- end }}
{{- with .Values.oauth.oidc.codeChallengeMethod }}
- name: OAUTH_CODE_CHALLENGE_METHOD
  value: {{ . | quote }}
{{- end }}
{{- end }}
