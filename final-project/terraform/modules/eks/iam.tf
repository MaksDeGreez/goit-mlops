# IAM roles that belong to the cluster:
#
#   * two roles for people, mapped to Kubernetes groups by access entries;
#   * one role for the EBS CSI driver, used through EKS Pod Identity.

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  cluster_arn = "arn:${data.aws_partition.current.partition}:eks:${var.region}:${data.aws_caller_identity.current.account_id}:cluster/${var.cluster_name}"
}

# ---------------------------------------------------------------------------
# Roles for people
# ---------------------------------------------------------------------------

# Anyone in this account may assume the two roles below. The account has one
# real user, so a longer list of principals would only pretend to be stricter.
# What the roles can do differs: in AWS both may only describe the cluster, and
# inside Kubernetes the group they are mapped to decides the rest.
data "aws_iam_policy_document" "human_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = [data.aws_caller_identity.current.account_id]
    }
  }
}

# Just enough to run "aws eks update-kubeconfig". Everything else a person may
# do is decided by the Kubernetes group of the access entry.
data "aws_iam_policy_document" "describe_cluster" {
  statement {
    effect    = "Allow"
    actions   = ["eks:DescribeCluster"]
    resources = [local.cluster_arn]
  }
}

resource "aws_iam_role" "mlops_engineer" {
  name               = "${var.cluster_name}-mlops-engineer"
  description        = "Cluster access for the platform team, Kubernetes group ${var.mlops_engineer_group}"
  assume_role_policy = data.aws_iam_policy_document.human_assume_role.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "mlops_engineer" {
  name   = "describe-cluster"
  role   = aws_iam_role.mlops_engineer.id
  policy = data.aws_iam_policy_document.describe_cluster.json
}

resource "aws_iam_role" "viewer" {
  name               = "${var.cluster_name}-viewer"
  description        = "Read only cluster access, Kubernetes group ${var.viewer_group}"
  assume_role_policy = data.aws_iam_policy_document.human_assume_role.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "viewer" {
  name   = "describe-cluster"
  role   = aws_iam_role.viewer.id
  policy = data.aws_iam_policy_document.describe_cluster.json
}

# ---------------------------------------------------------------------------
# Role for the EBS CSI driver
# ---------------------------------------------------------------------------

# EKS Pod Identity: the pods service, not an OIDC provider, assumes the role.
# sts:TagSession is required, the association fails without it.
data "aws_iam_policy_document" "pod_identity_assume_role" {
  statement {
    effect = "Allow"
    actions = [
      "sts:AssumeRole",
      "sts:TagSession",
    ]

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ebs_csi" {
  name               = "${var.cluster_name}-ebs-csi"
  description        = "Used by the aws-ebs-csi-driver add-on to create and attach volumes"
  assume_role_policy = data.aws_iam_policy_document.pod_identity_assume_role.json
  tags               = var.tags
}

# The AWS managed policy for the driver. The AWS documentation prints this ARN
# with a "service-role/" part in the middle, which does not exist.
resource "aws_iam_role_policy_attachment" "ebs_csi" {
  role       = aws_iam_role.ebs_csi.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonEBSCSIDriverPolicyV2"
}
