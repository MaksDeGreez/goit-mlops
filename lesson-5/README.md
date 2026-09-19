# Homework 2 — VPC and EKS cluster with Terraform

This folder builds the base infrastructure for the ML services of the next
assignments: a VPC with public and private subnets, and an EKS cluster with two
node groups inside it.

The work is split into two independent Terraform configurations. They are not
called from a shared root module. Instead the EKS configuration reads the
network ids from the state file of the VPC configuration, using
`terraform_remote_state`.

```
lesson-5/
├── vpc/                     # network, applied first
│   ├── main.tf              # terraform-aws-modules/vpc/aws
│   ├── variables.tf
│   ├── outputs.tf           # vpc_id, public_subnets, private_subnets
│   ├── terraform.tf         # required versions + aws provider
│   └── backend.tf           # S3 state, key vpc/terraform.tfstate
├── eks/                     # cluster, applied second
│   ├── main.tf              # terraform-aws-modules/eks/aws
│   ├── variables.tf
│   ├── outputs.tf
│   ├── terraform.tf
│   ├── backend.tf           # S3 state, key eks/terraform.tfstate
│   └── data.tf              # terraform_remote_state of the VPC
├── scripts/
│   └── create_state_bucket.sh
└── README.md
```

## What is created

**vpc/** uses the official module `terraform-aws-modules/vpc/aws`:

| Item | Value |
|---|---|
| VPC CIDR | `10.0.0.0/16` |
| Availability zones | `us-east-1a`, `us-east-1b` |
| Public subnets | `10.0.101.0/24`, `10.0.102.0/24` |
| Private subnets | `10.0.1.0/24`, `10.0.2.0/24` |
| Internet gateway | yes |
| NAT gateway | one, shared by both zones |

**eks/** uses the official module `terraform-aws-modules/eks/aws`:

| Item | Value |
|---|---|
| Cluster name | `goit-mlops-eks` |
| Kubernetes version | 1.35 |
| Node subnets | the private subnets |
| API endpoint | public, so `kubectl` works from a laptop |
| Add-ons | vpc-cni, kube-proxy, coredns, eks-pod-identity-agent |
| Node group `cpu-nodes` | 2 × `t4g.medium`, arm64, label `workload=cpu` |
| Node group `gpu-nodes` | 1 × `t3.medium`, x86_64, label `workload=gpu`, taint `workload=gpu:NoSchedule` |

### Why the nodes are in private subnets

The assignment shows `public_subnets` in its example, and that also works. This
project uses the private subnets instead, because that is how a real cluster is
built: the worker nodes get no public IP address, and nobody can reach them
from the internet. They still download container images, through the NAT
gateway. The public subnets stay free for load balancers, which are added in a
later assignment.

### Why `gpu-nodes` has no GPU

Real GPU instances (for example `g4dn.xlarge`) cost more than two dollars per
hour, which is too much for a study project. The assignment allows a second
node group that only simulates the split, so `gpu-nodes` runs a small `t3.medium`
instance.

The point of the group is the separation, and the separation is real:

* the nodes carry the label `workload=gpu`;
* the nodes carry the taint `workload=gpu:NoSchedule`, so nothing is scheduled
  there by accident. A pod has to ask for the group with a `nodeSelector` and a
  matching `toleration`.

The group has a second use as well. `cpu-nodes` runs on arm64 Graviton
instances, which are cheaper and match the developer laptop (Apple Silicon).
A small number of container images are still built only for x86_64, and those
can run on `gpu-nodes`.

## Before you start

You need:

* Terraform 1.10 or newer (the S3 backend uses `use_lockfile`, added in 1.10);
* AWS CLI v2, configured with a profile that may create VPC, EKS and IAM
  resources;
* `kubectl`.

All commands below assume the AWS profile is called `goit`:

```bash
export AWS_PROFILE=goit
aws sts get-caller-identity   # check the account before creating anything
```

If your profile has a different name, change `profile` in `vpc/backend.tf`,
`eks/backend.tf` and the default of the variable `aws_profile`.

### Create the state bucket once

Both configurations keep their state in the same S3 bucket, under different
keys. The bucket is created by a small script and is **not** managed by
Terraform on purpose: if it were, `terraform destroy` would delete the bucket
together with the state file inside it.

```bash
./scripts/create_state_bucket.sh
```

The script creates the bucket `mlops-tfstate-goit-447ede` in `us-east-1`,
blocks all public access, turns on versioning and turns on encryption. It can
be run again safely.

State locking uses a lock file in the same bucket (`use_lockfile = true`), so
no DynamoDB table is needed.

## How to run

The order matters: the EKS configuration reads the outputs of the VPC
configuration, so the VPC has to exist first.

### 1. Network

```bash
cd vpc
terraform init
terraform apply
```

Takes about 2 minutes, most of it the NAT gateway.

The outputs `vpc_id`, `public_subnets` and `private_subnets` are written into
the state file in S3:

```bash
terraform output
```

### 2. Cluster

```bash
cd ../eks
terraform init
terraform apply
```

Takes about 15 minutes: roughly 9 for the control plane and the rest for the
two node groups.

If you run this before the VPC exists, Terraform stops with
`Error: Unable to find remote state`. That is the dependency between the two
configurations working as intended.

## How to check the result

Add the cluster to the local kubeconfig:

```bash
aws eks --region us-east-1 --profile goit update-kubeconfig --name goit-mlops-eks
```

The same command is printed by `terraform output update_kubeconfig_command`.

Then look at the nodes:

```bash
kubectl get nodes -o wide
```

All nodes must be `Ready`. To see which node belongs to which group, and the
CPU architecture of each one:

```bash
kubectl get nodes -L workload,kubernetes.io/arch
```

To confirm the taint on the second group:

```bash
kubectl describe node -l workload=gpu | grep -i taint
```

The system pods should all be running:

```bash
kubectl get pods -A
```

## What the run produced

```
$ terraform apply          # in vpc/
Apply complete! Resources: 19 added, 0 changed, 0 destroyed.

$ terraform apply          # in eks/
Apply complete! Resources: 40 added, 0 changed, 0 destroyed.
```

```
$ kubectl get nodes -L workload,kubernetes.io/arch
NAME                         STATUS   ROLES    AGE   VERSION               WORKLOAD   ARCH
ip-10-0-1-13.ec2.internal    Ready    <none>   40m   v1.35.7-eks-cb19647   cpu        arm64
ip-10-0-1-251.ec2.internal   Ready    <none>   68m   v1.35.7-eks-cb19647   gpu        amd64
ip-10-0-2-94.ec2.internal    Ready    <none>   68m   v1.35.7-eks-cb19647   cpu        arm64

$ kubectl describe node -l workload=gpu | grep -i -A2 taint
Taints:             workload=gpu:NoSchedule
Unschedulable:      false
```

Two things to note in that output:

* every node address is inside `10.0.1.0/24` or `10.0.2.0/24`, which are the
  private subnets, so no worker node has a public address;
* the two groups really do differ: `arm64` for `cpu-nodes` and `amd64` for
  `gpu-nodes`, and only the second one carries the taint.

The Kubernetes version reported by the nodes is `v1.35.7-eks`, which matches the
version asked for in `variables.tf`.

Screenshots of all of these steps are in [`docs/`](docs/):

| File | What it shows |
|---|---|
| `01-vpc-apply.png` | `terraform apply` in `vpc/` and its outputs |
| `02-eks-apply.png` | `terraform apply` in `eks/` and its outputs |
| `03-kubectl-get-nodes.png` | all nodes in state `Ready` |
| `04-node-groups-and-taint.png` | the two node groups, both architectures, and the taint |

> The node names may differ between screenshots. The Auto Scaling group spreads
> the nodes evenly over the availability zones, and if both `cpu-nodes` start in
> the same zone it replaces one of them with a node in the other zone. The
> number of nodes stays the same.

## How to delete everything

The order is the opposite of the creation order, because the cluster depends on
the network. A VPC cannot be deleted while EKS still has network interfaces in
its subnets.

```bash
cd eks
terraform destroy

cd ../vpc
terraform destroy
```

The S3 state bucket stays. It costs a few cents per month and is reused by the
next assignments. Delete it only at the end of the course:

```bash
aws s3 rb s3://mlops-tfstate-goit-447ede --force
```

## Cost

Prices for `us-east-1`, on demand:

| Resource | Price per hour |
|---|---|
| EKS control plane | $0.10 |
| 2 × `t4g.medium` (cpu-nodes) | $0.067 |
| 1 × `t3.medium` (gpu-nodes) | $0.042 |
| NAT gateway | $0.045 |
| **Total** | **about $0.25** |

That is roughly $180 per month if the cluster is left running, so it is created
at the start of a working session and destroyed at the end of it. Only the S3
state bucket is kept.
