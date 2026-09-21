# Module `training-pipeline`

The Step Functions state machine that trains a new model version.

```
ValidateInput (Lambda)
   -> RunTrainingJob  (arn:aws:states:::eks:runJob.sync, namespace mlops-system)
   -> LogMetrics (Lambda)
any failure -> TrainingPipelineFailed (Fail)
```

Started with:

```json
{"image_tag": "abc1234", "git_sha": "039325b...", "params": {"max_iter": 50}}
```

The Job uses the service account `training`, `backoffLimit: 0`,
`restartPolicy: Never`, a read only root filesystem with `/tmp` as an
`emptyDir`, non-root user 10001 and about 1 GiB of memory. It deletes itself
`ttlSecondsAfterFinished` after it ends. The job name is built from the name of
the execution, so two runs never collide.

`LogOptions.RetrieveLogs` brings the last 100 lines of the pod back with the
result, which is how `LogMetrics` reads the `training_finished` line without
ever talking to Kubernetes. The line limit matters: the input and the output of
a state may not be larger than 256 KiB.

Things worth knowing:

* `eks:runJob.sync` calls the Kubernetes API from outside the VPC, so the
  cluster endpoint has to be public.
* In IAM the state machine only needs `eks:DescribeCluster`. What it may do
  **inside** the cluster comes from `aws_eks_access_entry`, which maps its role
  to the Kubernetes group `stepfunctions-runners`. The Role and RoleBinding for
  that group are in `final-project/rbac/` and must allow `batch/jobs` plus
  `pods` and `pods/log`, because `RetrieveLogs` reads the pod log.
* The Lambda source is in `final-project/lambda/`. Each function is one file
  and `archive_file` zips it into `build/`, which is not committed.
