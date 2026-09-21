{{- define "drift-monitor.name" -}}
drift-monitor
{{- end -}}

{{- define "drift-monitor.selectorLabels" -}}
app.kubernetes.io/name: drift-monitor
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "drift-monitor.labels" -}}
{{ include "drift-monitor.selectorLabels" . }}
app.kubernetes.io/part-of: mlops-final
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
{{- end -}}

{{- define "drift-monitor.image" -}}
{{ required "imageRegistry must be set by the ArgoCD Application" .Values.imageRegistry }}/final-project/drift-monitor:{{ .Values.imageTag }}
{{- end -}}
