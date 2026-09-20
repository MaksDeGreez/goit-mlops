output "state_machine_arn" {
  description = "ARN of the training state machine. Set it as the repository variable STATE_MACHINE_ARN in GitHub."
  value       = aws_sfn_state_machine.training.arn
}

output "state_machine_name" {
  description = "Name of the training state machine"
  value       = aws_sfn_state_machine.training.name
}

output "state_machine_role_arn" {
  description = "IAM role of the state machine. It is mapped to the Kubernetes group of the runners."
  value       = aws_iam_role.state_machine.arn
}

output "lambda_function_names" {
  description = "Names of the two functions of the pipeline"
  value = [
    aws_lambda_function.validate_input.function_name,
    aws_lambda_function.log_metrics.function_name,
  ]
}

output "log_group_names" {
  description = "CloudWatch log groups of the pipeline"
  value = [
    aws_cloudwatch_log_group.validate_input.name,
    aws_cloudwatch_log_group.log_metrics.name,
    aws_cloudwatch_log_group.state_machine.name,
  ]
}
