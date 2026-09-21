# Terraform

Two stacks. `infra` builds the AWS side, `platform` prepares the cluster and
the training pipeline. Everything that runs in the cluster is described in
`final-project/gitops/` and is deployed by Argo CD, not by Terraform.

```
modules/
  vpc                network, single NAT gateway
  eks                cluster, one arm64 node group, add-ons, access entries, IAM roles for people
  ecr                four image repositories
  ci-access          GitHub OIDC provider and the role GitHub Actions assumes
  argocd             the argo-cd chart and the root Application
  mlflow             S3 artifact bucket, Pod Identity role, the mlflow-postgres secret
  monitoring         the grafana-admin secret
  training-pipeline  two Lambdas, the Step Functions state machine, the EKS access entry
stacks/
  infra              vpc + eks + ecr + ci-access
  platform           namespaces + mlflow + monitoring + training-pipeline + argocd
```

State is in the S3 bucket `mlops-tfstate-goit-447ede` under
`final-project/infra/` and `final-project/platform/`. The bucket was created
once by hand and is not managed by Terraform, so no destroy can delete the
state it holds. Locking is `use_lockfile = true`, so there is no DynamoDB
table. The platform stack reads the outputs of the infra stack with
`terraform_remote_state`.

Everything else is a variable with a default, and the AWS profile is a variable
too (`aws_profile`, default `goit`). Only the `backend` blocks hardcode the
profile, because a backend block cannot use variables.

## Apply

```bash
cd stacks/infra
terraform init
terraform apply                       # about 15 minutes, most of it the cluster

aws eks update-kubeconfig --name mlops-final --region us-east-1 --profile goit

cd ../platform
terraform init
terraform apply                       # about 5 minutes
```

Then look at `terraform output` in both stacks. The useful ones are
`update_kubeconfig_command`, `ecr_repository_urls`, `ci_role_arn`,
`state_machine_arn`, `mlflow_artifact_bucket`, and the port-forward and
password commands. No password is printed by Terraform. The outputs give you
the `kubectl` command that reads the secret when you need it.

After `platform` is applied, Argo CD syncs the root Application and the rest of
the platform appears over the next few minutes.

## Destroy

**The order matters.** Argo CD puts a finalizer on every Application it
creates. If the controller is removed first, nothing is left to process those
finalizers and the namespace hangs in `Terminating` for ever.

Deleting the root Application removes every child Application and every
workload. It does not remove the two volume claims the StatefulSets made for
themselves: `data-postgres-0` in `mlops-system` and `storage-loki-0` in
`monitoring`. Argo CD did not create them, so it does not prune them, and each
one holds an EBS volume that keeps costing money. Delete them by hand.

```bash
# 1. Delete the root Application. Its finalizer removes every child
#    Application and every workload with it.
kubectl -n argocd delete application mlops-platform

# 2. Wait until no Application is left. Two or three minutes.
kubectl -n argocd get applications

# 3. Delete the two StatefulSet volume claims. Argo CD does not.
kubectl delete pvc --all -n mlops-system
kubectl delete pvc --all -n monitoring

# 4. Wait until the volumes are released. This must print nothing.
kubectl get pv

# 5. The platform stack.
cd stacks/platform
terraform destroy

# 6. The infra stack. Do this one last: it deletes the cluster the platform
#    stack was talking to.
cd ../infra
terraform destroy
```

Afterwards check that nothing is left. A load balancer or a volume created
inside the cluster is not in the Terraform state, so a destroy does not remove
it. That is the reason steps 1 to 4 come first.

```bash
export AWS_PROFILE=goit
aws eks list-clusters --region us-east-1
aws ec2 describe-volumes --region us-east-1 --query 'Volumes[].VolumeId'
aws ec2 describe-nat-gateways --region us-east-1 \
  --filter Name=state,Values=available --query 'NatGateways[].NatGatewayId'
aws elbv2 describe-load-balancers --region us-east-1 \
  --query 'LoadBalancers[].LoadBalancerArn'
```

If a namespace still hangs after all that, an Application finalizer is the
cause:

```bash
kubectl patch application <name> -n argocd --type=merge -p '{"metadata":{"finalizers":[]}}'
```

## Cost

Roughly $0.28 per hour, about $6.70 per day:

| Item | Per hour |
|---|---|
| EKS control plane | $0.10 |
| 2 x t4g.large | $0.134 |
| NAT gateway | $0.045 |
| S3, ECR, Lambda, Step Functions, CloudWatch | cents per month |

There is no free tier on this account, so the cluster is created at the start of
a working session and destroyed at the end of it.

## Checking the code without AWS

```bash
terraform fmt -check -recursive
cd stacks/infra    && terraform init -backend=false && terraform validate
cd ../platform     && terraform init -backend=false && terraform validate
```

`terraform plan` cannot check the platform stack before the infra stack is
applied. The cluster does not exist yet, so the Kubernetes and Helm providers
have nothing to connect to.
