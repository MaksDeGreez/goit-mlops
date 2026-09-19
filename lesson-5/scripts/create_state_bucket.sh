#!/usr/bin/env bash
#
# Creates the S3 bucket that stores Terraform state for this course.
#
# The bucket is created once and kept. It is NOT managed by the Terraform code
# in vpc/ or eks/ on purpose: if it were, "terraform destroy" would delete the
# bucket together with the state file it is supposed to protect.
#
# Terraform 1.10+ can lock state with a lock file inside the same bucket
# ("use_lockfile = true"), so no DynamoDB table is needed.
#
# The script is safe to run more than once.

set -euo pipefail

BUCKET="${BUCKET:-mlops-tfstate-goit-447ede}"
REGION="${REGION:-us-east-1}"
PROFILE="${AWS_PROFILE:-goit}"

echo "Bucket:  ${BUCKET}"
echo "Region:  ${REGION}"
echo "Profile: ${PROFILE}"
echo

aws_cmd() { aws --profile "${PROFILE}" --region "${REGION}" "$@"; }

if aws_cmd s3api head-bucket --bucket "${BUCKET}" 2>/dev/null; then
  echo "Bucket already exists, only re-applying settings."
else
  echo "Creating bucket..."
  # us-east-1 is the only region that must not get a LocationConstraint.
  if [ "${REGION}" = "us-east-1" ]; then
    aws_cmd s3api create-bucket --bucket "${BUCKET}"
  else
    aws_cmd s3api create-bucket --bucket "${BUCKET}" \
      --create-bucket-configuration "LocationConstraint=${REGION}"
  fi
fi

echo "Blocking all public access..."
aws_cmd s3api put-public-access-block --bucket "${BUCKET}" \
  --public-access-block-configuration \
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

echo "Enabling versioning (lets us recover an older state file)..."
aws_cmd s3api put-bucket-versioning --bucket "${BUCKET}" \
  --versioning-configuration "Status=Enabled"

echo "Enabling server-side encryption..."
aws_cmd s3api put-bucket-encryption --bucket "${BUCKET}" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true}]}'

echo
echo "Done. State bucket is ready: ${BUCKET}"
