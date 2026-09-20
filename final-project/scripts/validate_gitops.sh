#!/usr/bin/env bash
#
# Checks everything Argo CD would deploy, without a cluster.
#
#   1. helm lint on the three charts of this repository
#   2. helm template of the app-of-apps chart, with the values Terraform injects
#   3. helm template of our own charts, with the value files and the parameters
#      the rendered Applications really pass
#   4. helm template of every third-party chart, at the pinned version, with our
#      values file
#   5. kustomize build of the Grafana dashboards
#   6. kubeconform -strict over everything rendered, plus rbac/ and the
#      Postgres manifests
#
# Nothing is written down twice: the list of charts, versions, value files,
# parameters and namespaces is taken from the rendered Applications themselves.
# Change a chart version in gitops/bootstrap/values.yaml and this script checks
# the new one on the next run.
#
#   final-project/scripts/validate_gitops.sh
#
# Needs helm, yq, kustomize and kubeconform, and a network for the chart
# downloads and the schemas. It writes only into a temporary directory and
# removes it at the end.

set -euo pipefail

cd "$(dirname "$0")/.."

# Sample values. They never reach a cluster; they only have to look like the
# real thing, so that rendering takes the same branches as it will in AWS.
SAMPLE_REGISTRY="111122223333.dkr.ecr.us-east-1.amazonaws.com"
SAMPLE_REGION="us-east-1"
SAMPLE_BUCKET="mlops-final-mlflow-artifacts-abc123"
SAMPLE_CLUSTER="mlops-final"
SAMPLE_REPO="https://github.com/MaksDeGreez/goit-mlops.git"
SAMPLE_REVISION="final-project"
# Argo CD replaces $ARGOCD_APP_REVISION with the commit it is syncing.
SAMPLE_SHA="0123456789abcdef0123456789abcdef01234567"

# The API version the manifests are checked against. It is the version the
# cluster runs, so a field that was removed in 1.35 fails here.
KUBERNETES_VERSION="${KUBERNETES_VERSION:-1.35.0}"

# Schemas for the custom resources of this project: Application, Rollout and
# AnalysisTemplate. Without them kubeconform could only skip those objects.
CRD_SCHEMAS='https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'

# The one kind that is skipped, and the only one.
#
# The schema set kubeconform downloads has no schema for
# CustomResourceDefinition itself: the object holds a whole OpenAPI schema of
# its own inside spec.versions[].schema, which the generator leaves out. The
# Argo Rollouts chart ships five of them. -skip names that kind and nothing
# else, so every other unknown kind still fails the run; -ignore-missing-schemas
# would have hidden all of them at once.
SKIP_KINDS="CustomResourceDefinition"

if [ -t 1 ]; then
    BOLD=$(printf '\033[1m')
    GREEN=$(printf '\033[32m')
    RED=$(printf '\033[31m')
    OFF=$(printf '\033[0m')
else
    BOLD=""
    GREEN=""
    RED=""
    OFF=""
fi

step() {
    echo
    echo "${BOLD}==> $*${OFF}"
}

fail() {
    echo "${RED}FAILED: $*${OFF}" >&2
    exit 1
}

for tool in helm yq kustomize kubeconform; do
    command -v "$tool" >/dev/null 2>&1 || fail "$tool is not installed"
done

WORK_DIR="$(mktemp -d /tmp/final-project-gitops.XXXXXX)"
trap 'rm -rf "$WORK_DIR"' EXIT

RENDER_DIR="$WORK_DIR/rendered"
mkdir -p "$RENDER_DIR"

# One line per checked component, printed as a table at the end.
SUMMARY="$WORK_DIR/summary.tsv"
: >"$SUMMARY"

# yq reads a multi-document file one document at a time and prints a "---" line
# between them, plus an empty line for every document the query did not select.
# None of the queries below wants either, so both are dropped in one place.
yq_lines() {
    yq -r "$1" "$2" | sed -e '/^---$/d' -e '/^[[:space:]]*$/d'
}

# count_resources <file> -> how many documents with a "kind" it holds
count_resources() {
    yq_lines 'select(.kind != null) | .kind' "$1" | wc -l | tr -d ' '
}

# check <name> <file>: validate one rendered file and remember the result
check() {
    local name="$1" file="$2" count output skipped
    count="$(count_resources "$file")"
    [ "$count" -gt 0 ] || fail "$name rendered nothing"

    if ! output="$(kubeconform \
        -strict \
        -summary \
        -kubernetes-version "$KUBERNETES_VERSION" \
        -schema-location default \
        -schema-location "$CRD_SCHEMAS" \
        -skip "$SKIP_KINDS" \
        "$file" 2>&1)"; then
        echo "$output" >&2
        fail "kubeconform rejected $name"
    fi
    echo "    $output"

    skipped="$(printf '%s' "$output" | sed -n 's/.*Skipped: \([0-9]*\).*/\1/p')"
    printf '%s\t%s\t%s\n' "$name" "$count" "${skipped:-0}" >>"$SUMMARY"
}

step "versions"
helm version --short
kubeconform -v
kustomize version
yq --version

# ---------------------------------------------------------------------------
# 1. helm lint
# ---------------------------------------------------------------------------

step "helm lint: the three charts of this repository"
helm lint gitops/bootstrap --set imageRegistry="$SAMPLE_REGISTRY"
helm lint gitops/charts/inference \
    --values gitops/envs/staging.yaml --set imageRegistry="$SAMPLE_REGISTRY"
helm lint gitops/charts/inference \
    --values gitops/envs/production.yaml --set imageRegistry="$SAMPLE_REGISTRY"
helm lint gitops/charts/drift-monitor --set imageRegistry="$SAMPLE_REGISTRY"

# ---------------------------------------------------------------------------
# 2. the app of apps
# ---------------------------------------------------------------------------

step "helm template: the bootstrap chart, with the values Terraform injects"
BOOTSTRAP="$RENDER_DIR/bootstrap.yaml"
helm template mlops-platform gitops/bootstrap \
    --namespace argocd \
    --set repoURL="$SAMPLE_REPO" \
    --set targetRevision="$SAMPLE_REVISION" \
    --set imageRegistry="$SAMPLE_REGISTRY" \
    --set awsRegion="$SAMPLE_REGION" \
    --set mlflowArtifactBucket="$SAMPLE_BUCKET" \
    --set clusterName="$SAMPLE_CLUSTER" \
    >"$BOOTSTRAP"

check "bootstrap (Applications)" "$BOOTSTRAP"

# Every Helm parameter an Application passes has to be a key of the chart it
# passes it to. Argo CD would ignore a typo here without a word, which is
# exactly the kind of mistake this script is for.
step "parameters of our Applications against the values of our charts"
PARAMETERS="$WORK_DIR/parameters.tsv"
yq_lines '
  select(.kind == "Application") |
  select(.spec.source.helm.parameters != null) |
  .metadata.name as $app |
  .spec.source.path as $path |
  .spec.source.helm.parameters[] |
  [$app, $path, .name, .value] | @tsv
' "$BOOTSTRAP" >"$PARAMETERS"

[ -s "$PARAMETERS" ] || fail "no Application passes any parameter, which cannot be right"

while IFS=$'\t' read -r app path name _value; do
    # The path in an Application starts at the root of the repository, and this
    # script runs one level down, in final-project/.
    chart_dir="${path#final-project/}"
    if yq -e ".$name" "$chart_dir/values.yaml" >/dev/null 2>&1; then
        echo "  ok   $app -> $name"
    else
        fail "$app passes '$name', which is not a value of $chart_dir/values.yaml"
    fi
done <"$PARAMETERS"

# ---------------------------------------------------------------------------
# 3. our own charts, exactly as the Applications ask for them
# ---------------------------------------------------------------------------

step "helm template: our charts, with the value files and parameters of the Applications"
OWN_CHARTS="$WORK_DIR/own-charts.tsv"
yq_lines '
  select(.kind == "Application") |
  select(.spec.source.path != null and .spec.source.helm != null) |
  [.metadata.name,
   .spec.source.path,
   .spec.source.helm.releaseName,
   .spec.destination.namespace,
   ((.spec.source.helm.valueFiles // []) | join(","))] | @tsv
' "$BOOTSTRAP" >"$OWN_CHARTS"

while IFS=$'\t' read -r app path release namespace value_files; do
    chart_dir="${path#final-project/}"
    args=(template "$release" "$chart_dir" --namespace "$namespace")

    # A value file of a chart in this repository is relative to the chart
    # folder, which is how Argo CD reads it too.
    if [ -n "$value_files" ]; then
        IFS=',' read -r -a files <<<"$value_files"
        for file in "${files[@]}"; do
            args+=(--values "$chart_dir/$file")
        done
    fi

    # The parameters of this Application, one per line in parameters.tsv.
    while IFS=$'\t' read -r p_app _p_path p_name p_value; do
        [ "$p_app" = "$app" ] || continue
        args+=(--set-string "$p_name=${p_value/\$ARGOCD_APP_REVISION/$SAMPLE_SHA}")
    done <"$PARAMETERS"

    out="$RENDER_DIR/$app.yaml"
    echo "  $app: $chart_dir -> namespace $namespace"
    helm "${args[@]}" >"$out" || fail "helm template failed for $app"
    check "$app" "$out"

    # Production is rendered a second time with a model version filled in. Two
    # templates only exist once a version is pinned - the canary
    # AnalysisTemplate and the PostSync registry hook Job - and without this
    # pass they would never be checked, because the value file starts empty.
    if [ "$app" = "inference-production" ]; then
        promoted="$RENDER_DIR/$app-promoted.yaml"
        helm "${args[@]}" --set-string modelVersion=4 >"$promoted" ||
            fail "helm template failed for $app with a pinned model version"
        check "$app (with modelVersion 4)" "$promoted"
    fi
done <"$OWN_CHARTS"

# ---------------------------------------------------------------------------
# 4. the third-party charts, at the pinned versions
# ---------------------------------------------------------------------------

step "helm template: the third-party charts at the versions pinned in bootstrap/values.yaml"
THIRD_PARTY="$WORK_DIR/third-party.tsv"
yq_lines '
  select(.kind == "Application") |
  select(.spec.sources != null) |
  .metadata.name as $app |
  .spec.destination.namespace as $ns |
  .spec.sources[] | select(.chart != null) |
  [$app, .repoURL, .chart, .targetRevision, .helm.releaseName, $ns,
   ((.helm.valueFiles // []) | join(","))] | @tsv
' "$BOOTSTRAP" >"$THIRD_PARTY"

while IFS=$'\t' read -r app repo chart version release namespace value_files; do
    args=(template "$release" "$chart" --repo "$repo" --version "$version"
        --namespace "$namespace")

    if [ -n "$value_files" ]; then
        IFS=',' read -r -a files <<<"$value_files"
        for file in "${files[@]}"; do
            # "$values/final-project/gitops/..." is how an Application names a
            # file in this repository; this script already runs in
            # final-project/.
            args+=(--values "${file#\$values/final-project/}")
        done
    fi

    # Two Applications also pass a valuesObject (the MLflow bucket and region,
    # the OpenCost cluster name). Write it out and give it to helm as a file,
    # so that those branches are rendered as well.
    extra="$WORK_DIR/$app-extra.yaml"
    yq_lines "select(.metadata.name == \"$app\") | .spec.sources[0].helm.valuesObject // {}" \
        "$BOOTSTRAP" >"$extra"
    echo "  $app: $chart $version"
    if [ "$(cat "$extra")" != "{}" ]; then
        echo "         plus the valuesObject of the Application"
        args+=(--values "$extra")
    fi

    out="$RENDER_DIR/$app.yaml"
    helm "${args[@]}" >"$out" || fail "helm template failed for $app ($chart $version)"
    check "$app ($chart $version)" "$out"
done <"$THIRD_PARTY"

# ---------------------------------------------------------------------------
# 5. the dashboards and the plain manifests
# ---------------------------------------------------------------------------

step "kustomize build: the Grafana dashboards"
kustomize build gitops/apps/grafana-dashboards >"$RENDER_DIR/grafana-dashboards.yaml" ||
    fail "kustomize build failed"
check "grafana-dashboards (kustomize)" "$RENDER_DIR/grafana-dashboards.yaml"

step "kubeconform: the plain manifests"
# One object per file in rbac/, two files in postgres/. They are concatenated
# with a document separator so the counts read like the rendered charts.
collect() {
    local target="$1"
    shift
    : >"$target"
    for file in "$@"; do
        echo "---" >>"$target"
        cat "$file" >>"$target"
    done
}

collect "$RENDER_DIR/rbac.yaml" rbac/*.yaml
check "rbac (plain manifests)" "$RENDER_DIR/rbac.yaml"

collect "$RENDER_DIR/postgres.yaml" gitops/apps/postgres/*.yaml
check "postgres (plain manifests)" "$RENDER_DIR/postgres.yaml"

# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------

echo
echo "${BOLD}Summary${OFF}"
printf '| %-44s | %9s | %7s | %-6s |\n' "Component" "Resources" "Skipped" "Result"
printf '|%s|%s|%s|%s|\n' "----------------------------------------------" \
    "-----------" "---------" "--------"
total=0
total_skipped=0
while IFS=$'\t' read -r name count skipped; do
    printf '| %-44s | %9s | %7s | %-6s |\n' "$name" "$count" "$skipped" "ok"
    total=$((total + count))
    total_skipped=$((total_skipped + skipped))
done <"$SUMMARY"
printf '| %-44s | %9s | %7s | %-6s |\n' "total" "$total" "$total_skipped" ""

echo
echo "Every object was checked against a real schema: the built-in Kubernetes"
echo "schemas for $KUBERNETES_VERSION and the Argo CRD schemas from the datreeio"
echo "catalog. -ignore-missing-schemas is not used. The only kind that is"
echo "skipped is $SKIP_KINDS, which has no schema in that set;"
echo "the $total_skipped skipped objects are the CRDs of the Argo Rollouts chart."
echo
echo "${GREEN}GitOps checks passed.${OFF}"
