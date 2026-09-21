#!/usr/bin/env bash
# Checks the Kubernetes RBAC of the three groups against what rbac/README.md
# promises. Every line asks the cluster "can this group do that?" with
# "kubectl auth can-i" and compares the answer with the expected one.
#
# The caller must be a cluster admin, because impersonating a group
# (--as-group) is itself a permission.
set -uo pipefail

failed=0

# check <group> <expected yes|no> <verb> <resource> <namespace>
check() {
  local group="$1" expected="$2" verb="$3" resource="$4" namespace="$5" answer result
  local args=("$verb" "$resource")
  # A subresource such as pods/portforward is passed with --subresource. The
  # short "pods/portforward" form is answered with "no" by kubectl for some
  # verbs even when the rule exists, so it cannot be trusted here.
  if [[ "$resource" == */* ]]; then
    args=("$verb" "${resource%%/*}" "--subresource=${resource#*/}")
  fi
  answer="$(kubectl auth can-i "${args[@]}" -n "$namespace" \
    --as=rbac-check --as-group="$group" 2>/dev/null | head -1)"
  if [[ "$answer" == "$expected" ]]; then
    result="ok"
  else
    result="WRONG"
    failed=1
  fi
  printf '%-22s %-8s %-32s %-13s %-9s %-7s %s\n' \
    "$group" "$verb" "$resource" "$namespace" "$expected" "$answer" "$result"
}

printf '%-22s %-8s %-32s %-13s %-9s %-7s %s\n' GROUP VERB RESOURCE NAMESPACE EXPECTED ANSWER RESULT

# mlops-engineer: everything in staging
check mlops-engineers yes create rollouts.argoproj.io staging
check mlops-engineers yes delete pods staging
check mlops-engineers yes get secrets staging
check mlops-engineers yes create pods/exec staging
# mlops-engineer: limited in production. What runs there comes from Git only.
check mlops-engineers yes get pods production
check mlops-engineers yes get pods/log production
check mlops-engineers yes create pods/portforward production
check mlops-engineers yes patch rollouts.argoproj.io/status production
check mlops-engineers no get secrets production
check mlops-engineers no patch rollouts.argoproj.io production
check mlops-engineers no delete rollouts.argoproj.io production
check mlops-engineers no create pods/exec production
check mlops-engineers no delete pods production
# mlops-engineer: read only in the platform namespaces
check mlops-engineers yes get pods/log mlops-system
check mlops-engineers yes create pods/portforward monitoring
check mlops-engineers yes get applications.argoproj.io argocd
check mlops-engineers no create jobs mlops-system
check mlops-engineers no get secrets mlops-system

# viewer: read only, no secrets, no exec, no port-forward
check viewers yes get pods production
check viewers yes get pods/log production
check viewers yes get rollouts.argoproj.io production
check viewers yes get applications.argoproj.io argocd
check viewers no get secrets production
check viewers no create pods/portforward staging
check viewers no create pods/exec production
check viewers no delete pods staging
check viewers no patch applications.argoproj.io argocd

# the Step Functions role: training Jobs in mlops-system and nothing else
check stepfunctions-runners yes create jobs mlops-system
check stepfunctions-runners yes delete jobs mlops-system
check stepfunctions-runners yes get pods/log mlops-system
check stepfunctions-runners no create jobs production
check stepfunctions-runners no get secrets mlops-system

echo
if [[ "$failed" -eq 0 ]]; then
  echo "All 32 answers match rbac/README.md."
else
  echo "Some answers differ from what rbac/README.md promises." >&2
  exit 1
fi
