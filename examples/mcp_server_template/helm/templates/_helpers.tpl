{{/*
Expand the name of the chart.
*/}}
{{- define "{{NAME}}-mcp.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "{{NAME}}-mcp.fullname" -}}
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
Create chart name and version as used by the chart label.
*/}}
{{- define "{{NAME}}-mcp.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "{{NAME}}-mcp.labels" -}}
helm.sh/chart: {{ include "{{NAME}}-mcp.chart" . }}
{{ include "{{NAME}}-mcp.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "{{NAME}}-mcp.selectorLabels" -}}
app.kubernetes.io/name: {{ include "{{NAME}}-mcp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
MCP Server labels
*/}}
{{- define "{{NAME}}-mcp.mcpServerLabels" -}}
{{ include "{{NAME}}-mcp.labels" . }}
app.kubernetes.io/component: mcp-server
{{- end }}

{{/*
MCP Server selector labels
*/}}
{{- define "{{NAME}}-mcp.mcpServerSelectorLabels" -}}
{{ include "{{NAME}}-mcp.selectorLabels" . }}
app.kubernetes.io/component: mcp-server
{{- end }}

{{/*
Redis labels
*/}}
{{- define "{{NAME}}-mcp.redisLabels" -}}
{{ include "{{NAME}}-mcp.labels" . }}
app.kubernetes.io/component: redis
{{- end }}

{{/*
Redis selector labels
*/}}
{{- define "{{NAME}}-mcp.redisSelectorLabels" -}}
{{ include "{{NAME}}-mcp.selectorLabels" . }}
app.kubernetes.io/component: redis
{{- end }}

{{/*
Nginx labels
*/}}
{{- define "{{NAME}}-mcp.nginxLabels" -}}
{{ include "{{NAME}}-mcp.labels" . }}
app.kubernetes.io/component: nginx
{{- end }}

{{/*
Nginx selector labels
*/}}
{{- define "{{NAME}}-mcp.nginxSelectorLabels" -}}
{{ include "{{NAME}}-mcp.selectorLabels" . }}
app.kubernetes.io/component: nginx
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "{{NAME}}-mcp.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "{{NAME}}-mcp.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Redis URL
*/}}
{{- define "{{NAME}}-mcp.redisURL" -}}
{{- if .Values.redis.auth.enabled }}
redis://:{{ .Values.redis.auth.password }}@{{ include "{{NAME}}-mcp.fullname" . }}-redis:{{ .Values.redis.service.port }}
{{- else }}
redis://{{ include "{{NAME}}-mcp.fullname" . }}-redis:{{ .Values.redis.service.port }}
{{- end }}
{{- end }}
