{{/*
Generate image name
Usage: {{ include "coelho-search-mcp.imageName" (dict "appName" "fastapi" "root" .) }}
Images are specified with full registry path in values.yaml
*/}}
{{- define "coelho-search-mcp.imageName" -}}
{{- index .root.Values .appName "image" -}}
{{- end -}}


{{/*
Common environment variables for all services (non-sensitive)
Credentials are loaded from secret via secretRef
*/}}
{{- define "coelho-search-mcp.commonEnvVars" -}}
ENVIRONMENT: "{{ .Values.environment }}"
FASTAPI_HOST: "coelho-search-mcp-fastapi"
{{- end -}}

{{/*
ConfigMap settings
*/}}
{{- define "coelho-search-mcp.ConfigMapSettings" -}}
kind: ConfigMap
metadata:
  name: coelho-search-mcp-{{ .appName }}-configmap
  namespace: {{ .root.Release.Namespace }}
{{- end -}}


{{/*
Deployment settings
*/}}
{{- define "coelho-search-mcp.DeploymentSettings" -}}
kind: Deployment
metadata:
  name: coelho-search-mcp-{{ .appName }}
  namespace: {{ .root.Release.Namespace }}
  labels:
    app.kubernetes.io/name: {{ .root.Chart.Name }}
    app.kubernetes.io/instance: {{ .root.Release.Name }}
    app.kubernetes.io/version: {{ .root.Chart.AppVersion }}
    app.kubernetes.io/component: {{ .appName }}
    app.kubernetes.io/managed-by: {{ .root.Release.Service }}
{{- end -}}


{{/*
Service settings
*/}}
{{- define "coelho-search-mcp.ServiceSettings" -}}
kind: Service
metadata:
  name: coelho-search-mcp-{{ .appName }}
  namespace: {{ .root.Release.Namespace }}
  labels:
    app: coelho-search-mcp-{{ .appName }}
spec:
  selector:
    app: coelho-search-mcp-{{ .appName }}
{{- end -}}


{{/*
PVC settings
*/}}
{{- define "coelho-search-mcp.PVCSettings" -}}
kind: PersistentVolumeClaim
metadata:
  name: coelho-search-mcp-{{ .appName }}-pvc
  namespace: {{ .root.Release.Namespace }}
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: {{ index .root.Values .appName "storageSize" }}
  storageClassName: {{ index .root.Values .appName "storageClassName" }}
{{- end -}}


{{/*
Deployment spec settings
*/}}
{{- define "coelho-search-mcp.DeploymentSpecSettings" -}}
selector:
  matchLabels:
    app: coelho-search-mcp-{{ .appName }}
template:
  metadata:
    labels:
      app: coelho-search-mcp-{{ .appName }}
  spec:
    {{- if and (eq .root.Values.environment "production") (.root.Values.registry) (.root.Values.registry.imagePullSecret) }}
    imagePullSecrets:
      - name: {{ .root.Values.registry.imagePullSecret }}
    {{- end }}
    #securityContext:
    #  runAsNonRoot: true
    #  runAsUser: 1000
    #  fsGroup: 1000
    containers:
      - name: coelho-search-mcp-{{ .appName }}
        image: {{ include "coelho-search-mcp.imageName" (dict "appName" .appName "root" .root) }}
        imagePullPolicy: {{ index .root.Values .appName "imagePullPolicy" }}
        #securityContext:
        #  allowPrivilegeEscalation: false
        #  capabilities:
        #    drop:
        #      - ALL
        #  readOnlyRootFilesystem: false
        envFrom:
          - configMapRef:
              name: coelho-search-mcp-{{ .appName }}-configmap
        env:
          {{- include "coelho-search-mcp.secretEnvVars" .root | nindent 10 }}
{{- end -}}


{{/*
Secret environment variables - maps secret keys to env var names
Iterates over secretMappings defined in values.yaml
*/}}
{{- define "coelho-search-mcp.secretEnvVars" -}}
{{- range .Values.secretMappings }}
- name: {{ .envName }}
  valueFrom:
    secretKeyRef:
      name: {{ $.Values.secretName }}
      key: {{ .key }}
      optional: true
{{- end }}
{{- end -}}


{{- define "coelho-search-mcp.DeploymentResources" -}}
resources:
  requests:
    memory: {{ index .root.Values .appName "resources" "requests" "memory" }}
    cpu: {{ index .root.Values .appName "resources" "requests" "cpu" }}
  limits:
    memory: {{ index .root.Values .appName "resources" "limits" "memory" }}
    cpu: {{ index .root.Values .appName "resources" "limits" "cpu" }}
{{- end -}}


{{/*
Generate fullname for resources
*/}}
{{- define "coelho-search-mcp.fullname" -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}


{{/*
Common labels
*/}}
{{- define "coelho-search-mcp.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
{{ include "coelho-search-mcp.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}


{{/*
Selector labels
*/}}
{{- define "coelho-search-mcp.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}


{{/*
Service ports settings - ClusterIP for local (Skaffold), full portsSettings for production (ArgoCD)
Usage: {{ include "coelho-search-mcp.ServicePortsSettings" (dict "appName" "fastapi" "root" .) }}
*/}}
{{- define "coelho-search-mcp.ServicePortsSettings" -}}
{{- if eq .root.Values.environment "local" }}
  type: ClusterIP
  ports:
    {{- range (index .root.Values .appName "portsSettings" "ports") }}
    - name: {{ .name }}
      port: {{ .port }}
      targetPort: {{ .targetPort }}
      protocol: {{ .protocol }}
    {{- end }}
{{- else }}
  {{- toYaml (index .root.Values .appName "portsSettings") | nindent 2 }}
{{- end }}
{{- end -}}


{{/*
Probe settings - renders all probes (startup, liveness, readiness) for a container
Usage: {{ include "coelho-search-mcp.ProbeSettings" (dict "appName" "fastapi" "root" .) }}

Probe execution order:
1. startupProbe  - Runs ONLY during startup, disables liveness/readiness until success
2. livenessProbe - Runs after startup succeeds, restarts pod on failure
3. readinessProbe - Runs after startup succeeds, removes from Service on failure
*/}}
{{- define "coelho-search-mcp.ProbeSettings" -}}
{{- $appConfig := index .root.Values .appName -}}
{{- if $appConfig.startupProbeSettings }}
{{ toYaml $appConfig.startupProbeSettings }}
{{- end }}
{{- if $appConfig.livenessProbeSettings }}
{{ toYaml $appConfig.livenessProbeSettings }}
{{- end }}
{{- if $appConfig.readinessProbeSettings }}
{{ toYaml $appConfig.readinessProbeSettings }}
{{- end }}
{{- end -}}