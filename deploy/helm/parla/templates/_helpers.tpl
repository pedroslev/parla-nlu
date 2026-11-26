{{- define "parla.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "parla.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else if contains (include "parla.name" .) .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name (include "parla.name" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "parla.selectorLabels" -}}
app.kubernetes.io/name: {{ include "parla.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "parla.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{ include "parla.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/* Tag: image.tag or appVersion, plus "-<variant>" unless it's already there. */}}
{{- define "parla.image" -}}
{{- $tag := default .Chart.AppVersion .Values.image.tag }}
{{- with .Values.image.variant }}{{ if not (hasSuffix (printf "-%s" .) $tag) }}{{ $tag = printf "%s-%s" $tag . }}{{ end }}{{ end }}
{{- printf "%s:%s" .Values.image.repository $tag }}
{{- end }}

{{- define "parla.dataClaim" -}}
{{- default (printf "%s-data" (include "parla.fullname" .)) .Values.persistence.existingClaim }}
{{- end }}

{{/* Secret names: the existing one, or the one this chart creates (secret.yaml). */}}
{{- define "parla.metricsSecret" -}}
{{- default (printf "%s-metrics" (include "parla.fullname" .)) .Values.metrics.existingSecret }}
{{- end }}
{{- define "parla.otelSecret" -}}
{{- default (printf "%s-otel" (include "parla.fullname" .)) .Values.otel.existingSecret }}
{{- end }}
{{- define "parla.oidcSecret" -}}
{{- default (printf "%s-oidc" (include "parla.fullname" .)) .Values.oidc.existingSecret }}
{{- end }}
{{- define "parla.databaseSecret" -}}
{{- default (printf "%s-database" (include "parla.fullname" .)) .Values.database.existingSecret }}
{{- end }}
{{- define "parla.secretKeySecret" -}}
{{- default (printf "%s-secret-key" (include "parla.fullname" .)) .Values.secretKey.existingSecret }}
{{- end }}
{{- define "parla.secretKeyEnabled" -}}
{{- if or .Values.secretKey.value .Values.secretKey.existingSecret .Values.secrets.encrypt }}true{{ end }}
{{- end }}
{{- define "parla.postgres" -}}
{{- if or .Values.database.url .Values.database.existingSecret }}true{{ end }}
{{- end }}
{{/* High availability: more than one pod (replicaCount > 1 or autoscaling). Checked here so every template agrees. */}}
{{- define "parla.ha" -}}
{{- if or (gt (int .Values.replicaCount) 1) .Values.autoscaling.enabled }}
{{- if not (include "parla.postgres" .) }}{{ fail "replicaCount > 1 and autoscaling need Postgres: set database.url or database.existingSecret (docs/kubernetes.md#high-availability)" }}{{ end }}
{{- if not (include "parla.secretKeyEnabled" .) }}{{ fail "replicaCount > 1 and autoscaling need secretKey.value, secretKey.existingSecret or secrets.encrypt (PARLA_SECRET_KEY, the same in every replica)" }}{{ end }}
{{- if and .Values.persistence.enabled (not .Values.persistence.existingClaim) (not (has "ReadWriteMany" .Values.persistence.accessModes)) }}{{ fail "replicaCount > 1 and autoscaling share the data volume: persistence.accessModes must include ReadWriteMany (or use persistence.existingClaim)" }}{{ end }}
true
{{- end }}
{{- end }}
{{- define "parla.oidcEnabled" -}}
{{- if and .Values.oidc.issuer .Values.oidc.clientId }}true{{ end }}
{{- end }}

{{- define "parla.hosts" -}}
{{- $hosts := .Values.config.hosts }}
{{- if and .Values.ingress.enabled .Values.ingress.exposeAdmin }}{{ $hosts = concat $hosts .Values.ingress.hosts }}{{ end }}
{{- $hosts | uniq | join "," }}
{{- end }}

{{- define "parla.secureCookie" -}}
{{- if kindIs "bool" .Values.config.secureCookie }}{{ ternary "1" "" .Values.config.secureCookie }}
{{- else if and .Values.ingress.enabled .Values.ingress.exposeAdmin .Values.ingress.tls }}1{{ end }}
{{- end }}

{{- define "parla.env" -}}
- {name: PARLA_FUNCTIONS, value: {{ ternary "1" "0" .Values.config.functions | quote }}}
- {name: PARLA_WHISPER, value: {{ .Values.config.whisper | quote }}}
{{- with .Values.config.lang }}
- {name: PARLA_LANG, value: {{ . | quote }}}
{{- end }}
{{- with .Values.config.publicUrl }}
- {name: PARLA_PUBLIC_URL, value: {{ . | quote }}}
{{- end }}
{{- with include "parla.hosts" . }}
- {name: PARLA_HOSTS, value: {{ . | quote }}}
{{- end }}
{{- with include "parla.secureCookie" . }}
- {name: PARLA_SECURE_COOKIE, value: {{ . | quote }}}
{{- end }}
{{- if not (kindIs "invalid" .Values.config.retentionDays) }}
- {name: PARLA_RETENTION_DAYS, value: {{ .Values.config.retentionDays | toString | quote }}}
{{- end }}
{{- if not (kindIs "invalid" .Values.config.auditDays) }}
- {name: PARLA_AUDIT_DAYS, value: {{ .Values.config.auditDays | toString | quote }}}
{{- end }}
{{- with .Values.config.logFormat }}
- {name: PARLA_LOG_FORMAT, value: {{ . | quote }}}
{{- end }}
{{- if .Values.metrics.enabled }}
- {name: PARLA_METRICS, value: "1"}
{{- if or .Values.metrics.token .Values.metrics.existingSecret }}
- name: PARLA_METRICS_TOKEN
  valueFrom: {secretKeyRef: {name: {{ include "parla.metricsSecret" . }}, key: {{ .Values.metrics.secretKey }}}}
{{- end }}
{{- end }}
{{- with .Values.otel.endpoint }}
- {name: PARLA_OTEL_ENDPOINT, value: {{ . | quote }}}
{{- end }}
{{- with .Values.otel.serviceName }}
- {name: OTEL_SERVICE_NAME, value: {{ . | quote }}}
{{- end }}
{{- with .Values.otel.resourceAttributes }}
- {name: OTEL_RESOURCE_ATTRIBUTES, value: {{ . | quote }}}
{{- end }}
{{- if .Values.otel.content }}
- {name: PARLA_OTEL_CONTENT, value: "1"}
{{- end }}
{{- if or .Values.otel.headers .Values.otel.existingSecret }}
- name: OTEL_EXPORTER_OTLP_HEADERS
  valueFrom: {secretKeyRef: {name: {{ include "parla.otelSecret" . }}, key: {{ .Values.otel.secretKey }}}}
{{- end }}
{{- if include "parla.oidcEnabled" . }}
- {name: PARLA_OIDC_ISSUER, value: {{ .Values.oidc.issuer | quote }}}
- {name: PARLA_OIDC_CLIENT_ID, value: {{ .Values.oidc.clientId | quote }}}
{{- if or .Values.oidc.clientSecret .Values.oidc.existingSecret }}
- {name: PARLA_OIDC_CLIENT_SECRET_FILE, value: {{ printf "/run/secrets/parla-oidc/%s" .Values.oidc.secretKey | quote }}}
{{- end }}
{{- range $k, $v := dict "SCOPES" .Values.oidc.scopes "ROLE_CLAIM" .Values.oidc.roleClaim "ROLE_MAP" .Values.oidc.roleMap "DEFAULT_ROLE" .Values.oidc.defaultRole "LABEL" .Values.oidc.label }}
{{- if $v }}
- {name: PARLA_OIDC_{{ $k }}, value: {{ $v | quote }}}
{{- end }}
{{- end }}
{{- if .Values.oidc.only }}
- {name: PARLA_OIDC_ONLY, value: "1"}
{{- end }}
{{- if not .Values.oidc.logout }}
- {name: PARLA_OIDC_LOGOUT, value: "0"}
{{- end }}
{{- end }}
{{- if include "parla.postgres" . }}
- name: PARLA_DATABASE_URL
  valueFrom: {secretKeyRef: {name: {{ include "parla.databaseSecret" . }}, key: {{ .Values.database.secretKey }}}}
{{- if not (kindIs "invalid" .Values.database.pool) }}
- {name: PARLA_DB_POOL, value: {{ .Values.database.pool | toString | quote }}}
{{- end }}
{{- end }}
{{- if include "parla.secretKeyEnabled" . }}
- name: PARLA_SECRET_KEY
  valueFrom: {secretKeyRef: {name: {{ include "parla.secretKeySecret" . }}, key: {{ .Values.secretKey.secretKey }}}}
{{- end }}
{{- with .Values.extraEnv }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{- define "parla.ollamaLabels" -}}
app.kubernetes.io/name: {{ include "parla.name" . }}-ollama
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
{{- define "parla.ollamaEnv" -}}
- {name: HOME, value: /models}                 # ollama keeps its key in ~/.ollama
- {name: OLLAMA_MODELS, value: /models/models}
- {name: OLLAMA_HOST, value: "0.0.0.0:11434"}
{{- end }}
{{- define "parla.ollamaMounts" -}}
- {name: models, mountPath: /models}
- {name: tmp, mountPath: /tmp}
{{- end }}
