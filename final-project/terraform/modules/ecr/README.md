# Module `ecr`

One ECR repository per service image: `final-project/training`,
`final-project/inference`, `final-project/registry-ops`,
`final-project/drift-monitor`.

Every repository has scan on push, immutable tags, AES256 encryption, a
lifecycle rule that keeps the last 10 images and `force_delete = true` so
`terraform destroy` never stops on a repository that still holds images.

Immutable tags mean that pushing the same git commit twice is refused. CI tags
images with the commit, so that only happens when a workflow is re-run on an
unchanged commit.

The output `registry_url` is built from the account id. It is the value
Terraform injects into the root Argo CD Application, so the account id never
appears in Git.
