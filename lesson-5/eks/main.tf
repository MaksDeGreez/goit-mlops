# EKS cluster placed in the VPC that the vpc/ configuration created.
# All network ids come from the VPC state through data.terraform_remote_state.

locals {
  # Worker nodes go into the private subnets, so they have no public IP address
  # and reach the internet only through the NAT gateway. The public subnets are
  # left for load balancers, which we will add in a later assignment.
  private_subnets = data.terraform_remote_state.vpc.outputs.private_subnets
  vpc_id          = data.terraform_remote_state.vpc.outputs.vpc_id
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.0"

  name               = var.cluster_name
  kubernetes_version = var.kubernetes_version

  vpc_id                   = local.vpc_id
  subnet_ids               = local.private_subnets
  control_plane_subnet_ids = local.private_subnets

  # The API server must be reachable from the laptop for "kubectl get nodes".
  endpoint_public_access = true

  # Gives the IAM user that runs terraform admin rights inside the cluster,
  # so "aws eks update-kubeconfig" is enough to start using kubectl.
  enable_cluster_creator_admin_permissions = true

  # Keep the control plane logs cheap: this is a short-lived learning cluster.
  cloudwatch_log_group_retention_in_days = 7

  # By default the module creates a KMS key to encrypt Kubernetes secrets.
  # A KMS key costs about $1 per month and, once deleted, still waits several
  # days before it disappears. This cluster is created and destroyed again in
  # every working session, so every session would leave another key behind.
  # The cluster stores no real secrets, so the key is turned off here.
  create_kms_key           = false
  encryption_config        = null
  attach_encryption_policy = false

  # Cluster add-ons managed by Terraform, so their versions are part of the
  # code and not something that was clicked in the console.
  # The two marked "before_compute" have to exist before the nodes join:
  # vpc-cni gives pods their network, and the pod identity agent lets pods
  # use IAM roles later on.
  addons = {
    coredns    = {}
    kube-proxy = {}
    vpc-cni = {
      before_compute = true
    }
    eks-pod-identity-agent = {
      before_compute = true
    }
  }

  # Two node groups, one for each kind of workload.
  #
  # cpu-nodes is arm64 (Graviton). Graviton instances are cheaper than the x86
  # ones and match the developer laptop, which is Apple Silicon.
  #
  # gpu-nodes plays the role of the GPU pool. Real GPU instances such as g4dn
  # are far too expensive for a learning project, so this group uses a small
  # x86 instance instead. The assignment allows this. What matters is that the
  # cluster really has two separate pools, and that a pod can be sent to one of
  # them on purpose. That is done with the node label and the taint below:
  # only pods with a matching toleration and nodeSelector land on gpu-nodes.
  # The group is also useful in practice, because a few container images are
  # still built for x86 only.
  eks_managed_node_groups = {
    cpu-nodes = {
      ami_type       = "AL2023_ARM_64_STANDARD"
      instance_types = var.cpu_instance_types
      capacity_type  = "ON_DEMAND"

      min_size     = 1
      max_size     = 4
      desired_size = 2

      labels = {
        workload = "cpu"
      }
    }

    gpu-nodes = {
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = var.gpu_instance_types
      capacity_type  = "ON_DEMAND"

      min_size     = 1
      max_size     = 2
      desired_size = 1

      labels = {
        workload = "gpu"
      }

      # Nothing runs here unless it asks for it.
      taints = {
        gpu = {
          key    = "workload"
          value  = "gpu"
          effect = "NO_SCHEDULE"
        }
      }
    }
  }
}
