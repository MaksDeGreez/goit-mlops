#!/usr/bin/env bash
#
# Checks the Terraform code without touching AWS.
#
#   1. terraform fmt -check -recursive   over the whole terraform/ folder
#   2. per stack: terraform init -backend=false, then terraform validate
#
# -backend=false is what makes this work with no credentials: Terraform then
# never contacts the S3 state bucket. It still downloads the providers and the
# modules, so the first run needs a network and takes a minute.
#
# The same script runs in GitHub Actions (job "terraform") and in GitLab CI.
#
#   final-project/scripts/validate_terraform.sh
#
# It can be started from anywhere and exits non-zero on the first real failure.

set -euo pipefail

cd "$(dirname "$0")/.."

TERRAFORM_DIR="terraform"
STACKS=(infra platform)

# Colours, but only when the output is a terminal. CI logs stay plain.
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

command -v terraform >/dev/null 2>&1 || fail "terraform is not installed"

step "terraform version"
terraform version

step "terraform fmt -check -recursive $TERRAFORM_DIR"
if terraform fmt -check -recursive "$TERRAFORM_DIR"; then
    echo "every file is formatted"
else
    fail "some files are not formatted. Run: terraform fmt -recursive $TERRAFORM_DIR"
fi

# The result of every stack, collected for the table at the end.
results=()

for stack in "${STACKS[@]}"; do
    step "stack $stack: terraform init -backend=false"
    (
        cd "$TERRAFORM_DIR/stacks/$stack"
        # -input=false so a missing value fails instead of waiting for someone
        # to type it. -backend=false skips the S3 backend entirely.
        terraform init -backend=false -input=false -no-color
    ) || fail "terraform init failed in stack $stack"

    step "stack $stack: terraform validate"
    (
        cd "$TERRAFORM_DIR/stacks/$stack"
        terraform validate -no-color
    ) || fail "terraform validate failed in stack $stack"

    results+=("$stack")
done

echo
echo "${BOLD}Summary${OFF}"
echo "| Stack    | fmt | init | validate |"
echo "|----------|-----|------|----------|"
for stack in "${results[@]}"; do
    printf "| %-8s | ok  | ok   | ok       |\n" "$stack"
done
echo
echo "${GREEN}Terraform checks passed.${OFF}"
echo
echo "Note: this is not a plan. 'terraform plan' needs AWS credentials, and the"
echo "platform stack cannot even be planned before the infra stack is applied,"
echo "because its Kubernetes and Helm providers have no cluster to talk to."
