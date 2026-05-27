output "function_name" {
  value       = length(aws_lambda_function.judgment) > 0 ? aws_lambda_function.judgment[0].function_name : var.function_name
  description = "Judgment Lambda function name."
}

output "function_arn" {
  value       = length(aws_lambda_function.judgment) > 0 ? aws_lambda_function.judgment[0].arn : null
}

output "execution_role_arn" {
  value       = length(aws_iam_role.judgment_execution) > 0 ? aws_iam_role.judgment_execution[0].arn : null
}

output "schedule_rule_name" {
  value       = length(aws_cloudwatch_event_rule.daily_judgment) > 0 ? aws_cloudwatch_event_rule.daily_judgment[0].name : null
  description = "EventBridge rule name for scheduled judgment runs."
}

output "schedule_rule_arn" {
  value       = length(aws_cloudwatch_event_rule.daily_judgment) > 0 ? aws_cloudwatch_event_rule.daily_judgment[0].arn : null
}

output "cloudwatch_log_group_name" {
  value       = length(aws_cloudwatch_log_group.judgment) > 0 ? aws_cloudwatch_log_group.judgment[0].name : null
  description = "Lambda CloudWatch log group name."
}

output "cloudwatch_log_group_arn" {
  value       = length(aws_cloudwatch_log_group.judgment) > 0 ? aws_cloudwatch_log_group.judgment[0].arn : null
  description = "Lambda CloudWatch log group ARN."
}
