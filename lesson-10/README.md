# Homework 5 — Automating model training with AWS Step Functions and CI

This project creates a small training pipeline in AWS and starts it automatically after every push.

The pipeline is an AWS Step Functions state machine with two steps. Each step calls its own Lambda
function:

```
push to the repository
        │
        ▼
   CI pipeline  ──►  aws stepfunctions start-execution
                              │
                              ▼
                     ┌──────────────────┐
                     │  ValidateData    │  Lambda: check the input data
                     └────────┬─────────┘
                              │  output becomes the input of the next step
                     ┌────────▼─────────┐
                     │   LogMetrics     │  Lambda: log the metrics of the run
                     └──────────────────┘
```

The whole infrastructure is described in Terraform. In a real project the same structure would be
extended with training, evaluation and model registry steps.

## Project structure

```
lesson-10/
├── terraform/
│   ├── main.tf              # Lambda functions, IAM roles, Step Functions state machine
│   ├── data.tf              # account information and IAM policy documents
│   ├── terraform.tf         # provider and version requirements
│   ├── variables.tf         # input variables with defaults
│   ├── oidc.tf              # access for CI without a stored AWS key
│   ├── outputs.tf           # ARNs needed by the CI settings
│   └── lambda/
│       ├── validate.py      # step 1: check the input data
│       ├── log_metrics.py   # step 2: log the metrics
│       ├── validate.zip     # archive uploaded to Lambda
│       └── log_metrics.zip  # archive uploaded to Lambda
├── .gitlab-ci.yml           # the same pipeline written for GitLab CI
└── README.md
```

The GitHub Actions workflow is at **`.github/workflows/train-model.yml`** in the root of the
repository. GitHub only reads workflows from that folder, so it cannot live inside `lesson-10/`.
Its full text is included at the end of this file.

## Requirements

| Tool | Version | Used for |
|---|---|---|
| Terraform | 1.5 or newer | creating the infrastructure |
| AWS CLI | 2.x | starting and checking the pipeline |
| zip | any | packing the Lambda code |
| Docker + gitlab-ci-local | optional | testing the GitLab file locally |

An AWS profile with permission to create IAM roles, Lambda functions and Step Functions is needed.
The profile name is set by the `aws_profile` variable and is `goit` by default.

## How to deploy

### 1. Create the Lambda archives

AWS Lambda accepts the code as a zip archive, so both functions are packed before Terraform runs:

```bash
cd terraform/lambda
zip validate.zip validate.py
zip log_metrics.zip log_metrics.py
```

After this the folder contains two Python files and two archives. If the Python code is changed, the
archives have to be created again. Terraform notices the change through `source_code_hash` and
uploads the new version.

### 2. Create the infrastructure

```bash
cd terraform
terraform init
terraform apply
```

Terraform creates 12 resources:

- two Lambda functions on **arm64** (about 20 percent cheaper than x86_64), runtime `python3.13`;
- one IAM role for the Lambda functions, allowed only to write their own logs;
- one IAM role for the state machine, allowed to call only these two functions;
- the Step Functions state machine `ValidateData → LogMetrics`;
- two CloudWatch log groups with a retention of 7 days;
- an OIDC provider and a role for CI (see below).

After `apply` Terraform prints the values needed for the CI settings:

```bash
terraform output
```

```
aws_region              = "us-east-1"
github_actions_role_arn = "arn:aws:iam::<account-id>:role/mlops-train-automation-github-actions-role"
state_machine_arn       = "arn:aws:states:us-east-1:<account-id>:stateMachine:mlops-train-automation-pipeline"
state_machine_name      = "mlops-train-automation-pipeline"
lambda_function_names   = [
  "mlops-train-automation-validate",
  "mlops-train-automation-log-metrics",
]
```

### 3. Add the variables to the CI settings

In GitHub: **Settings → Secrets and variables → Actions → Variables**. Three repository variables
are needed:

| Variable | Value |
|---|---|
| `AWS_ROLE_ARN` | value of the `github_actions_role_arn` output |
| `STATE_MACHINE_ARN` | value of the `state_machine_arn` output |
| `AWS_REGION` | `us-east-1` |

These are variables and not secrets, because an ARN is not a password. They are still kept outside
the code so that the account number is not written in a public repository.

## Access to AWS without a stored key (OIDC)

The repository is public, so no AWS key may be stored in it. Instead the pipeline uses OpenID
Connect:

1. GitHub creates a short lived token for every workflow run. The token says which repository and
   which branch the run belongs to.
2. AWS trusts tokens from `token.actions.githubusercontent.com`. This trust is the
   `aws_iam_openid_connect_provider` resource in `oidc.tf`.
3. The workflow sends the token to AWS and receives temporary credentials that are valid for one
   hour. Nothing is stored anywhere.

The role can only be used by this exact repository and branch. This is the condition in `oidc.tf`:

```hcl
condition {
  test     = "StringLike"
  variable = "token.actions.githubusercontent.com:sub"
  values = [
    "repo:${var.github_repository}:ref:refs/heads/${var.github_branch}",
    "repo:${local.repo_owner}@*/${local.repo_name}@*:ref:refs/heads/${var.github_branch}",
  ]
}
```

There are two patterns because GitHub sends this claim in two shapes. The documented one is
`repo:owner/name:ref:refs/heads/branch`, but the token that arrived in the first run of this pipeline
looked like this:

```
repo:MaksDeGreez@178340907/goit-mlops@1359527131:ref:refs/heads/lesson-10
```

GitHub adds the numeric id of the owner and of the repository. A check with `StringEquals` on the
documented shape does not match that string, and the first run failed with
`Not authorized to perform sts:AssumeRoleWithWebIdentity`. The exact claim was found in CloudTrail,
in the `AssumeRoleWithWebIdentity` event. `StringLike` with both patterns accepts either shape.

The wildcards are only in place of the numeric ids, so the rule is still strict: another owner,
another repository or another branch does not match.

The role is also allowed to do very little: start this one state machine and read the result of the
run. It cannot create, change or delete anything.

For the workflow to be able to ask for the token, it needs this permission:

```yaml
permissions:
  id-token: write
```

## How the CI pipeline works

The job `train-model` runs after every push to the `lesson-10` branch and does four things:

1. asks AWS for temporary credentials using the OIDC token;
2. starts the state machine with `aws stepfunctions start-execution` and passes a JSON input;
3. waits until the run is finished, checking the status every 5 seconds;
4. prints the result and fails the job if the status is not `SUCCEEDED`.

Step 4 matters: without it the job would be green even when the pipeline in AWS failed.

### The input JSON

The CI job passes the short commit hash into the pipeline, so every run can be traced back to the
code that started it:

```json
{
  "source": "github-actions",
  "commit": "4989830",
  "rows": 150
}
```

The GitLab file sends the same structure with `"source": "gitlab-ci"`.

## The GitLab CI file

The task asks for GitLab CI. The project is hosted on GitHub, so the workflow that really runs is
the GitHub Actions one, and `.gitlab-ci.yml` is the same pipeline written for GitLab. It uses the
image `amazon/aws-cli:2.15.0`, the job name `train-model` and the same
`aws stepfunctions start-execution` command with `--input`.

The GitLab file was **not** written and left untested. It was checked with
[gitlab-ci-local](https://github.com/firecow/gitlab-ci-local), a tool that runs GitLab jobs in
Docker on a local machine without a GitLab account:

```bash
npm install -g gitlab-ci-local

cd lesson-10
gitlab-ci-local train-model \
  --variable AWS_ACCESS_KEY_ID=... \
  --variable AWS_SECRET_ACCESS_KEY=... \
  --variable AWS_SESSION_TOKEN=... \
  --variable STATE_MACHINE_ARN=...
```

Result of the local run:

```
train-model starting amazon/aws-cli:2.15.0 (train)
train-model > Input: {"source":"gitlab-ci","commit":"610f14dc","rows":150}
train-model > Started: arn:aws:states:...:execution:mlops-train-automation-pipeline:train-1788734910
train-model > Attempt 1: SUCCEEDED
train-model > Result of the pipeline:
train-model > {"source": "gitlab-ci", ..., "metrics": {"rows_used": 150, "accuracy": 0.93, "loss": 0.21}, "status": "completed"}
train-model finished in 18 s

 PASS  train-model
```

So the file is valid GitLab CI syntax and it really starts the pipeline in AWS.

On GitLab the credentials would come from OIDC as well, through `id_tokens` and
`aws sts assume-role-with-web-identity`. When the file runs locally there is no GitLab token, so the
job uses the credentials from the environment instead. Both cases are handled in the script.

## How to check the pipeline manually

### From the AWS Console

1. Open **Step Functions → State machines → `mlops-train-automation-pipeline`**.
2. Press **Start execution** and paste the input:

   ```json
   {"source": "manual", "commit": "test001", "rows": 150}
   ```

3. Press **Start execution**. The graph shows both steps in green and the status becomes `Succeeded`.
4. The logs of each function are in **CloudWatch → Log groups →
   `/aws/lambda/mlops-train-automation-validate`**.

### From the command line

```bash
STATE_MACHINE_ARN=$(cd terraform && terraform output -raw state_machine_arn)

EXECUTION_ARN=$(aws stepfunctions start-execution \
  --state-machine-arn "$STATE_MACHINE_ARN" \
  --name "manual-$(date +%s)" \
  --input '{"source":"manual","commit":"test001","rows":150}' \
  --query executionArn --output text)

aws stepfunctions describe-execution --execution-arn "$EXECUTION_ARN" \
  --query '{status:status,output:output}'
```

A successful run returns:

```json
{
  "source": "manual",
  "commit": "test001",
  "rows": 150,
  "validation": {"status": "passed", "rows": 150, "checked_fields": ["source", "commit"]},
  "metrics": {"rows_used": 150, "accuracy": 0.93, "loss": 0.21},
  "status": "completed"
}
```

### What happens with wrong input

If a required field is missing, the first Lambda raises an error and the pipeline stops. The second
step is not started:

```bash
aws stepfunctions start-execution --state-machine-arn "$STATE_MACHINE_ARN" \
  --name "bad-$(date +%s)" --input '{"source":"manual"}'
```

```
status: FAILED
error:  ValueError
cause:  Missing required fields: commit
```

This shows that the validation step really controls the pipeline and does not only print a message.

## Cost

The resources cost almost nothing when the pipeline is idle:

| Resource | Price |
|---|---|
| Step Functions | $0.025 per 1000 state transitions, one run is 4 transitions |
| Lambda (arm64, 128 MB) | fractions of a cent per run |
| CloudWatch Logs | a few kilobytes per run, deleted after 7 days |

There is nothing that runs all the time, so there is no hourly cost. Still, the resources should be
deleted after the work is checked.

## How to delete everything

```bash
cd terraform
terraform destroy
```

This deletes all 12 resources, including the log groups and the OIDC provider.

## The GitHub Actions workflow

The file below is `.github/workflows/train-model.yml` from the root of the repository. It is copied
here so that this folder can be read on its own.

```yaml
name: train-model

on:
  push:
    branches:
      - lesson-10
    paths:
      - "lesson-10/**"
      - ".github/workflows/train-model.yml"
  workflow_dispatch:

permissions:
  id-token: write
  contents: read

jobs:
  train-model:
    name: Start the training pipeline
    runs-on: ubuntu-latest

    steps:
      - name: Check out the repository
        uses: actions/checkout@v4

      - name: Get temporary AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ vars.AWS_ROLE_ARN }}
          aws-region: ${{ vars.AWS_REGION }}
          role-session-name: github-actions-train-model

      - name: Start the Step Functions execution
        id: start
        run: |
          INPUT=$(printf '{"source":"github-actions","commit":"%s","rows":150}' "${GITHUB_SHA:0:7}")
          EXECUTION_ARN=$(aws stepfunctions start-execution \
            --state-machine-arn "${{ vars.STATE_MACHINE_ARN }}" \
            --name "train-$(date +%s)" \
            --input "$INPUT" \
            --query executionArn --output text)
          echo "execution_arn=$EXECUTION_ARN" >> "$GITHUB_OUTPUT"

      - name: Wait for the pipeline to finish
        run: |
          EXECUTION_ARN="${{ steps.start.outputs.execution_arn }}"
          for attempt in $(seq 1 30); do
            STATUS=$(aws stepfunctions describe-execution \
              --execution-arn "$EXECUTION_ARN" --query status --output text)
            [ "$STATUS" != "RUNNING" ] && break
            sleep 5
          done
          aws stepfunctions describe-execution \
            --execution-arn "$EXECUTION_ARN" --query output --output text
          if [ "$STATUS" != "SUCCEEDED" ]; then exit 1; fi
```

## Submission

- Branch: [`lesson-10`](https://github.com/MaksDeGreez/goit-mlops/tree/lesson-10)
- The archive is created from the root of the repository:

  ```bash
  zip -r ДЗ10_Слєпцов_Максім.zip lesson-10/ \
    -x "lesson-10/terraform/.terraform/*" \
       "lesson-10/terraform/.terraform.lock.hcl" \
       "lesson-10/terraform/terraform.tfstate*" \
       "lesson-10/terraform/tfplan" \
       "lesson-10/terraform/lambda/__pycache__/*"
  unzip -l ДЗ10_Слєпцов_Максім.zip
  ```

  The exclusions matter. After `terraform init` the folder `.terraform` holds the downloaded
  provider and is about 780 MB, and the state file describes the created infrastructure. Neither
  belongs in the archive.
