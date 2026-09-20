# Module `ci-access`

GitHub OIDC provider and the one IAM role GitHub Actions assumes. No AWS access
key is ever stored in the repository.

The role may:

* get an ECR login token (`*` resource, the call has no resource of its own);
* push and read images in the four project repositories;
* start the training state machine and read its own execution.

Nothing else. It cannot create, change or delete infrastructure.

Two things are easy to get wrong and are handled here:

1. GitHub sends the subject claim with **immutable numeric ids**, for example
   `repo:owner@178340907/name@1359527131:ref:refs/heads/final-project`. A
   `StringEquals` condition never matches. Both shapes are allowed with
   `StringLike`.
2. The state machine lives in the other stack, so its ARN is built from the
   name. Reading it from the platform stack would make the two stacks depend on
   each other in both directions.

The workflow needs `permissions: id-token: write`.
