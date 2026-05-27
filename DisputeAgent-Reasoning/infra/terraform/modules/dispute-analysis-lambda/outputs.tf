output "function_name" {
  value       = length(aws_lambda_function.analysis) > 0 ? aws_lambda_function.analysis[0].function_name : var.function_name
  description = "Analysis Lambda function name."
}

output "function_arn" {
  value       = length(aws_lambda_function.analysis) > 0 ? aws_lambda_function.analysis[0].arn : null
  description = "Analysis Lambda ARN when created by this module."
}

output "execution_role_arn" {
  value       = length(aws_iam_role.analysis_execution) > 0 ? aws_iam_role.analysis_execution[0].arn : null
  description = "IAM role ARN for the analysis Lambda."
}

output "execution_role_name" {
  value       = length(aws_iam_role.analysis_execution) > 0 ? aws_iam_role.analysis_execution[0].name : null
  description = "IAM role name for the analysis Lambda."
}

output "stream_event_source_mapping_uuid" {
  value       = length(aws_lambda_event_source_mapping.dispute_core_stream) > 0 ? aws_lambda_event_source_mapping.dispute_core_stream[0].uuid : null
  description = "DynamoDB stream mapping UUID when attach_stream_event_source is true."
}

output "sqs_event_source_mapping_uuid" {
  value       = length(aws_lambda_event_source_mapping.sqs) > 0 ? aws_lambda_event_source_mapping.sqs[0].uuid : null
  description = "SQS mapping UUID when attach_sqs_event_source is true."
}

output "cloudwatch_log_group_name" {
  value       = length(aws_cloudwatch_log_group.analysis) > 0 ? aws_cloudwatch_log_group.analysis[0].name : null
  description = "Lambda CloudWatch log group name."
}

output "cloudwatch_log_group_arn" {
  value       = length(aws_cloudwatch_log_group.analysis) > 0 ? aws_cloudwatch_log_group.analysis[0].arn : null
  description = "Lambda CloudWatch log group ARN."
}
