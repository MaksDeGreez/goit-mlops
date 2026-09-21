# Terraform logs of the real deployment

These are the last lines of the four Terraform runs of the deployment that the screenshots
show. The account id and the network ids are replaced with placeholders.

## infra-apply

```text
module.eks.module.eks.module.eks_managed_node_group["main"].module.user_data.null_resource.validate_cluster_service_cidr: Creation complete after 0s [id=<accoun
module.eks.module.eks.module.eks_managed_node_group["main"].aws_launch_template.this[0]: Creation complete after 6s [id=lt-0770313b08eceb01a]
module.eks.module.eks.module.eks_managed_node_group["main"].aws_eks_node_group.this[0]: Creation complete after 1m49s [id=mlops-final:main-bd8b3eecda2bcb9fe8be3
module.eks.module.eks.aws_eks_addon.this["coredns"]: Creation complete after 15s [id=mlops-final:coredns]
module.eks.module.eks.aws_eks_addon.this["kube-proxy"]: Creation complete after 25s [id=mlops-final:kube-proxy]
module.eks.module.eks.aws_eks_addon.this["aws-ebs-csi-driver"]: Creation complete after 46s [id=mlops-final:aws-ebs-csi-driver]
...
Apply complete! Resources: 75 added, 0 changed, 0 destroyed.
```

## platform-apply

```text
module.training_pipeline.aws_lambda_function.validate_input: Creation complete after 16s [id=mlops-final-validate-input]
module.training_pipeline.aws_lambda_function.log_metrics: Creation complete after 23s [id=mlops-final-log-metrics]
module.training_pipeline.aws_iam_role_policy.state_machine: Creation complete after 0s [id=mlops-final-training-pipeline:run-the-training-pipeline]
module.training_pipeline.aws_sfn_state_machine.training: Creation complete after 37s [id=arn:aws:states:us-east-1:<account-id>:stateMachine:mlops-final-training
module.argocd.helm_release.argocd: Creation complete after 1m12s [id=argocd]
module.argocd.helm_release.argocd_apps: Creation complete after 3s [id=argocd-apps]
...
Apply complete! Resources: 31 added, 0 changed, 0 destroyed.
```

## platform-destroy

```text
module.training_pipeline.aws_iam_role.lambda: Destruction complete after 1s
kubernetes_namespace_v1.this["argocd"]: Destruction complete after 14s
kubernetes_namespace_v1.this["mlops-system"]: Destruction complete after 14s
kubernetes_namespace_v1.this["staging"]: Destruction complete after 14s
kubernetes_namespace_v1.this["monitoring"]: Destruction complete after 14s
kubernetes_namespace_v1.this["production"]: Destruction complete after 14s
...
Destroy complete! Resources: 31 destroyed.
```

## infra-destroy

```text
module.eks.module.eks.aws_security_group_rule.node["ingress_cluster_6443_webhook"]: Destruction complete after 5s
module.eks.module.eks.aws_security_group_rule.node["ingress_cluster_443"]: Destruction complete after 6s
module.eks.module.eks.aws_security_group_rule.node["ingress_nodes_ephemeral"]: Destruction complete after 7s
module.eks.module.eks.aws_security_group.node[0]: Destruction complete after 1s
module.eks.module.eks.aws_security_group.cluster[0]: Destruction complete after 1s
module.vpc.module.vpc.aws_vpc.this[0]: Destruction complete after 1s
...
Destroy complete! Resources: 75 destroyed.
```
