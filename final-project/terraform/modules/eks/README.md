# Module `eks`

Wraps `terraform-aws-modules/eks/aws` (~> 21.0) and adds the IAM roles that
belong to the cluster.

Creates:

* the cluster `mlops-final`, public endpoint on (Step Functions needs it),
  `authentication_mode = "API"`, no customer managed KMS key (see the comment
  in `main.tf`);
* one managed node group `main`: 2 x `t4g.large`, `AL2023_ARM_64_STANDARD`,
  private subnets, 50 GiB gp3 root volume;
* add-ons `coredns`, `kube-proxy`, `vpc-cni` (prefix delegation),
  `eks-pod-identity-agent`, `aws-ebs-csi-driver` (gp3 default StorageClass,
  Pod Identity);
* IAM roles `<cluster>-mlops-engineer` and `<cluster>-viewer`, assumable by any
  principal of the account, plus the access entries that map them to the
  Kubernetes groups `mlops-engineers` and `viewers`;
* the IAM role of the EBS CSI driver.

The Role and RoleBinding objects for those groups are **not** here. They are
plain manifests in `final-project/rbac/` and Argo CD applies them.
