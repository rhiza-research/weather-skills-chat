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
