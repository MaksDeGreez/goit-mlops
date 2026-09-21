# The state machine definition, written with jsonencode so the editor checks
# the brackets and Terraform fills in the ARNs.
#
# A key that ends in ".$" takes its value from the input of the state instead
# of from a constant. That is how the image, the job name, the arguments and
# the commit reach the Kubernetes Job.

locals {
  # Retrying these means retrying a problem on the AWS side, never a failed
  # validation and never a failed training run.
  lambda_retry = [{
    ErrorEquals = [
      "Lambda.ServiceException",
      "Lambda.TooManyRequestsException",
      "Lambda.AWSLambdaException",
      "Lambda.SdkClientException",
    ]
    IntervalSeconds = 2
    MaxAttempts     = 3
    BackoffRate     = 2
  }]

  catch_everything = [{
    ErrorEquals = ["States.ALL"]
    # Keeps the original input and adds the error under $.error, so the reason
    # is visible in the execution history next to what was asked for.
    ResultPath = "$.error"
    Next       = "TrainingPipelineFailed"
  }]

  training_job = {
    apiVersion = "batch/v1"
    kind       = "Job"

    metadata = {
      "name.$" = "$.job_name"
      labels = {
        "app.kubernetes.io/name"      = "training"
        "app.kubernetes.io/part-of"   = var.name_prefix
        "app.kubernetes.io/component" = "training-job"
      }
    }

    spec = {
      # No retry. A failed training run has to be looked at, and a silent
      # second attempt would only hide the reason.
      backoffLimit = 0

      # The Job object and its pod delete themselves after this, so finished
      # runs do not pile up. It is long enough to look at the pod by hand.
      ttlSecondsAfterFinished = var.job_ttl_seconds

      # The pipeline does not wait forever if the pod hangs.
      activeDeadlineSeconds = var.job_deadline_seconds

      template = {
        metadata = {
          labels = {
            "app.kubernetes.io/name"    = "training"
            "app.kubernetes.io/part-of" = var.name_prefix
          }
        }

        spec = {
          # The service account is created by Argo CD. It needs no AWS rights:
          # the job only talks to MLflow, and MLflow owns the S3 bucket.
          serviceAccountName = var.training_service_account
          restartPolicy      = "Never"

          securityContext = {
            runAsNonRoot = true
            runAsUser    = 10001
            runAsGroup   = 10001
            fsGroup      = 10001
            seccompProfile = {
              type = "RuntimeDefault"
            }
          }

          containers = [{
            name = "training"

            # "<repository>:<tag>", built by the ValidateInput function.
            "image.$" = "$.image"

            # The image already starts "python -m training.run", so only the
            # options are passed. The list is empty when the pipeline was
            # started without training parameters.
            "args.$" = "$.args"

            env = [
              {
                name  = "MLFLOW_TRACKING_URI"
                value = var.mlflow_tracking_uri
              },
              {
                name  = "MODEL_NAME"
                value = var.model_name
              },
              {
                name  = "EXPERIMENT_NAME"
                value = var.experiment_name
              },
              {
                # The image has no git in it, so the commit is passed in. It
                # becomes a tag of the new model version.
                name      = "GIT_SHA"
                "value.$" = "$.git_sha"
              },
              {
                # The root filesystem is read only, so everything that writes a
                # temporary file has to be sent to the mounted /tmp.
                name  = "HOME"
                value = "/tmp"
              },
              {
                name  = "TMPDIR"
                value = "/tmp"
              },
            ]

            resources = {
              requests = {
                cpu    = var.job_cpu_request
                memory = var.job_memory_request
              }
              limits = {
                memory = var.job_memory_limit
              }
            }

            securityContext = {
              allowPrivilegeEscalation = false
              readOnlyRootFilesystem   = true
              capabilities = {
                drop = ["ALL"]
              }
            }

            volumeMounts = [{
              name      = "tmp"
              mountPath = "/tmp"
            }]
          }]

          volumes = [{
            name     = "tmp"
            emptyDir = {}
          }]
        }
      }
    }
  }

  definition = jsonencode({
    Comment = "Train a new version of the ${var.model_name} model and record its metrics"
    StartAt = "ValidateInput"

    States = {
      ValidateInput = {
        Type     = "Task"
        Comment  = "Check the input and build the image reference, the job name and the arguments"
        Resource = aws_lambda_function.validate_input.arn

        # The name of the execution is unique, and the job name is built from
        # it, so two runs can never collide on the same Job object.
        Parameters = {
          "input.$"          = "$"
          "execution_name.$" = "$$.Execution.Name"
        }

        Retry = local.lambda_retry
        Catch = local.catch_everything
        Next  = "RunTrainingJob"
      }

      RunTrainingJob = {
        Type     = "Task"
        Comment  = "Run the training job in the cluster and wait for it to finish"
        Resource = "arn:aws:states:::eks:runJob.sync"

        Parameters = merge(local.job_parameters, {
          Job = local.training_job
        })

        # Keep the output of ValidateInput and put the job result next to it,
        # so the last state sees both.
        ResultPath     = "$.job"
        TimeoutSeconds = var.job_deadline_seconds

        Catch = local.catch_everything
        Next  = "LogMetrics"
      }

      LogMetrics = {
        Type     = "Task"
        Comment  = "Find the training_finished line in the logs of the job and record it"
        Resource = aws_lambda_function.log_metrics.arn

        Retry = local.lambda_retry
        Catch = local.catch_everything
        End   = true
      }

      TrainingPipelineFailed = {
        Type  = "Fail"
        Error = "TrainingPipelineFailed"
        Cause = "The training pipeline stopped. Open the failed state in the execution history: it holds the error, and for a failed job also the last lines the pod printed."
      }
    }
  })

  job_parameters = {
    ClusterName = var.cluster_name
    # Step Functions talks to the API server itself, so it needs the address
    # and the certificate. They come from the infra stack.
    CertificateAuthority = var.cluster_certificate_authority_data
    Endpoint             = var.cluster_endpoint
    Namespace            = var.namespace

    # Brings the output of the pod back as part of the result, which is how
    # the last state reads the metrics without talking to Kubernetes at all.
    # The whole state input and output may not be larger than 256 KiB, so the
    # number of lines is limited.
    LogOptions = {
      RetrieveLogs = true
      LogParameters = {
        tailLines = [tostring(var.job_log_tail_lines)]
      }
    }
  }
}
