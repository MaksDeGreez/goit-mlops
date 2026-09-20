{{/*
Two blocks that every Application repeats. They are here so that a change to
the sync behaviour is made once instead of thirteen times.
*/}}

{{/*
The second source of a multi-source Application: this repository, used only as
a place to read value files from. The first source stays the Helm repository of
the chart, so Argo CD still shows the real chart version. A value file is then
written as $values/<path>.
*/}}
{{- define "bootstrap.valuesSource" -}}
- repoURL: {{ .Values.repoURL | quote }}
  targetRevision: {{ .Values.targetRevision | quote }}
  ref: values
{{- end -}}

{{/*
Sync policy. Takes a dict with an optional "extraSyncOptions" list.

prune removes what was deleted from Git, selfHeal puts back what somebody
changed by hand in the cluster. Both are what makes this GitOps and not just a
one-time install.
*/}}
{{- define "bootstrap.syncPolicy" -}}
syncPolicy:
  automated:
    prune: true
    selfHeal: true
  syncOptions:
    # Terraform owns the namespaces, because it also puts the secrets in them.
    - CreateNamespace=false
    {{- range .extraSyncOptions }}
    - {{ . }}
    {{- end }}
  retry:
    limit: 5
    backoff:
      duration: 15s
      factor: 2
      maxDuration: 3m
{{- end -}}
