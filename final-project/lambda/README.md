# Lambda functions of the training pipeline

Two small functions. They are the first and the last step of the Step Functions
state machine that trains a new model version:

```
ValidateInput  ->  RunTrainingJob (a Kubernetes Job in the cluster)  ->  LogMetrics
```

| File | Handler | What it does |
|---|---|---|
| `validate_input.py` | `validate_input.lambda_handler` | checks the input of the execution and builds the image reference, the job name and the command line of the training job |
| `log_metrics.py` | `log_metrics.lambda_handler` | reads the logs the Job printed, finds the `training_finished` line and writes the metrics to CloudWatch |

Both use the standard library only, so each function is packaged as a single
file. Terraform zips them with `archive_file` into
`terraform/modules/training-pipeline/build/`, which is not committed. Because
of that, each file has its own small `log()` helper instead of a shared module.
A shared file would have to be copied into both packages for six lines of code.

## Input and output

The pipeline is started with:

```json
{"image_tag": "abc1234", "git_sha": "039325b...", "params": {"max_iter": 50}}
```

`params` is optional. Only the training options listed in `ALLOWED_PARAMS` are
accepted. A typo in the CI input then fails the execution instead of becoming
an unknown flag on the command line. The state machine adds the name of the
execution, which is what makes the job name unique.

`LogMetrics` receives the output of the Job step. With
`LogOptions.RetrieveLogs` turned on it looks like this:

```json
{"job": {"logs": {"pods": {"<pod>": {"containers": {"<container>": {"log": "...\n..."}}}}}}}
```

The pod name is only known at run time, so the function walks the whole object
and reads every piece of text it finds. It keeps the **last** line that parses
as JSON and has `"event": "training_finished"`. If there is no such line, the
job did not finish properly. The function then raises, which fails the
execution.

## Tests

No AWS and no network:

```bash
cd final-project/lambda
uv sync --locked
uv run pytest
```

The two handlers need nothing at run time, so `uv.lock` pins only pytest and
what pytest brings with it. It is committed anyway, so CI installs exactly
the versions that were used here.

49 tests: the input checks, the parameter allow list, the job name limit of 63
characters, the log parsing for both log shapes, the missing-result case and
the shape of the JSON log line.
