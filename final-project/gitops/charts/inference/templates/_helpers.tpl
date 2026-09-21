{{/*
Names and labels.

Every namespace holds exactly one release of this chart, so the objects can
keep the plain name "inference". The scripts, the port-forward commands and the
LogQL query of the drift job all use that name, and a generated one would make
them depend on the release name.
*/}}

{{- define "inference.name" -}}
inference
{{- end -}}

{{/*
The two labels that identify a pod of this release. They are also the selector
of the Rollout, so they must never change for a running release.
*/}}
{{- define "inference.selectorLabels" -}}
app.kubernetes.io/name: inference
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "inference.labels" -}}
{{ include "inference.selectorLabels" . }}
app.kubernetes.io/part-of: mlops-final
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
{{- end -}}

{{/*
The image of a service. The registry host holds the AWS account id, so it is
never in this repository: the Application passes it in and rendering stops here
when it is missing.
*/}}
{{- define "inference.registry" -}}
{{ required "imageRegistry must be set by the ArgoCD Application" .Values.imageRegistry }}
{{- end -}}

{{- define "inference.image" -}}
{{ include "inference.registry" . }}/final-project/inference:{{ .Values.imageTag }}
{{- end -}}

{{- define "inference.registryOpsImage" -}}
{{ include "inference.registry" . }}/final-project/registry-ops:{{ .Values.registryOpsImageTag }}
{{- end -}}

{{/*
The same hardening for every container of this chart.
*/}}
{{- define "inference.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop:
    - ALL
{{- end -}}

{{- define "inference.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 10001
runAsGroup: 10001
seccompProfile:
  type: RuntimeDefault
{{- end -}}
