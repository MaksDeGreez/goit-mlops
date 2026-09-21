# EKS cluster with one arm64 node group, the add-ons the platform needs and
# the access entries that map IAM roles to Kubernetes groups.
#
# The Kubernetes RBAC objects for those groups are not created here. They are
# plain manifests in final-project/rbac/ and are deployed by Argo CD, so the
# permissions of a group can be reviewed in Git next to everything else.

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.0"

  name               = var.cluster_name
  kubernetes_version = var.kubernetes_version

  vpc_id                   = var.vpc_id
  subnet_ids               = var.subnet_ids
  control_plane_subnet_ids = var.subnet_ids

  # The public endpoint is required, not a convenience: the Step Functions
  # integration arn:aws:states:::eks:runJob.sync calls the Kubernetes API from
  # outside the VPC and cannot reach a private-only endpoint.
  endpoint_public_access = true

  # Access entries only. The old aws-auth ConfigMap is not used anywhere in
  # this project, so there is no second place where permissions can be granted.
  authentication_mode = "API"

  # Gives the identity that runs terraform admin rights inside the cluster, so
  # "aws eks update-kubeconfig" is enough to start using kubectl.
  enable_cluster_creator_admin_permissions = true

  # Control plane logs are cheap to keep for a week and are the only way to see
  # why the API server refused something.
  cloudwatch_log_group_retention_in_days = var.log_retention_days

  # Kubernetes secret encryption with a customer managed KMS key is turned off
  # on purpose. A KMS key costs about $1 per month and, once deleted, still
  # waits days before it disappears, so every apply/destroy cycle of this
  # project would leave another key behind. Secrets are still encrypted by AWS
  # at rest in etcd, and the only secrets here are generated passwords that are
  # recreated on every apply. The module tests encryption_config against null,
  # not against an empty object: an empty object gives an encryption block
  # without a key ARN and the apply fails.
  create_kms_key           = false
  encryption_config        = null
  attach_encryption_policy = false

  # Add-ons managed by Terraform, so their versions are part of the code and
  # not something that was clicked in the console. Versions are not pinned:
  # most_recent (the module default) picks the newest build that AWS offers for
  # this Kubernetes version.
  #
  # vpc-cni and the pod identity agent must exist before the nodes join, hence
  # before_compute. Forgetting it on vpc-cni is the trap that silently leaves
  # every node at 17 pods instead of 110.
  addons = {
    coredns    = {}
    kube-proxy = {}

    vpc-cni = {
      before_compute = true

      # Prefix delegation. Without it a t4g.large gets 3 network interfaces x
      # (12 - 1) addresses = 33 pods. With it the node hands out /28 prefixes
      # and reaches the 110 pod limit of a managed node group. The values of
      # the env map must be strings, numbers and booleans are rejected.
      configuration_values = jsonencode({
        env = {
          ENABLE_PREFIX_DELEGATION = "true"
          WARM_PREFIX_TARGET       = "1"
        }
      })
    }

    eks-pod-identity-agent = {
      before_compute = true
    }

    # Since EKS 1.30 a new cluster has no StorageClass at all, so every PVC
    # would stay Pending forever. This add-on brings the EBS driver and creates
    # a gp3 default class. It talks to the EC2 API through Pod Identity, so no
    # IRSA role and no static keys are needed.
    aws-ebs-csi-driver = {
      configuration_values = jsonencode({
        defaultStorageClass = {
          enabled = true
        }
      })

      pod_identity_association = [{
        role_arn        = aws_iam_role.ebs_csi.arn
        service_account = "ebs-csi-controller-sa"
      }]
    }
  }

  # One node group. Every workload of this project is arm64, and a second group
  # would only add cost. The size is driven by memory: MLflow, Prometheus,
  # Loki, Grafana and about twelve inference pods together ask for roughly
  # 9 GiB, which fits on two t4g.large (2 x 8 GiB) with room to spare.
  eks_managed_node_groups = {
    main = {
      ami_type       = "AL2023_ARM_64_STANDARD"
      instance_types = var.instance_types
      capacity_type  = "ON_DEMAND"

      min_size     = var.node_min_size
      max_size     = var.node_max_size
      desired_size = var.node_desired_size

      # The module always builds its own launch template, and disk_size is
      # ignored when it does, so the root volume is described here. The
      # default 20 GiB is not enough: the training image alone is about 1 GB
      # and several large images are pulled onto the same node.
      block_device_mappings = {
        root = {
          device_name = "/dev/xvda"
          ebs = {
            volume_size           = var.node_disk_size
            volume_type           = "gp3"
            encrypted             = true
            delete_on_termination = true
          }
        }
      }

      labels = {
        workload = "general"
      }
    }
  }

  # IAM roles get cluster access through access entries. Each role is mapped to
  # a Kubernetes group; the Role and RoleBinding objects for those groups live
  # in final-project/rbac/.
  access_entries = {
    mlops_engineer = {
      principal_arn     = aws_iam_role.mlops_engineer.arn
      kubernetes_groups = [var.mlops_engineer_group]
      type              = "STANDARD"
    }

    viewer = {
      principal_arn     = aws_iam_role.viewer.arn
      kubernetes_groups = [var.viewer_group]
      type              = "STANDARD"
    }
  }

  tags = var.tags
}
