output "state_machine_arn" {
  description = "ARN of the state machine. Set it as the STATE_MACHINE_ARN variable in the CI settings."
  value       = aws_sfn_state_machine.train_pipeline.arn
}

output "state_machine_name" {
  description = "Name of the state machine"
  value       = aws_sfn_state_machine.train_pipeline.name
}

output "github_actions_role_arn" {
  description = "ARN of the CI role. Set it as the AWS_ROLE_ARN variable in the CI settings."
  value       = aws_iam_role.github_actions.arn
}

output "lambda_function_names" {
  description = "Names of the two Lambda functions"
  value = [
    aws_lambda_function.validate.function_name,
    aws_lambda_function.log_metrics.function_name,
  ]
}

output "aws_region" {
  description = "Region where the pipeline was created"
  value       = data.aws_region.current.region
}
