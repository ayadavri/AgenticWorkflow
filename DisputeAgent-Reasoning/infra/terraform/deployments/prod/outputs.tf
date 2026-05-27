output "dispute_core_table_name" {
  value       = module.dispute_core_dynamodb.table_name
  description = "DisputeCore DynamoDB table name."
}

output "dispute_core_table_arn" {
  value       = module.dispute_core_dynamodb.table_arn
  description = "DisputeCore DynamoDB table ARN."
}

output "dispute_core_stream_arn" {
  value       = module.dispute_core_dynamodb.stream_arn
  description = "DisputeCore DynamoDB stream ARN."
}

output "dispute_core_stream_lambda_function_name" {
  value       = module.dispute_core_dynamodb.stream_lambda_function_name
  description = "Lambda consuming the DisputeCore stream (bootstrap Lambda when Terraform creates it)."
}

output "dispute_core_stream_lambda_arn" {
  value       = module.dispute_core_dynamodb.stream_lambda_arn
  description = "ARN of Terraform-managed bootstrap Lambda, when created."
}

output "dispute_core_stream_lambda_event_source_mapping_uuid" {
  value       = module.dispute_core_dynamodb.stream_lambda_event_source_mapping_uuid
  description = "Event source mapping UUID when Terraform created the stream attachment."
}

output "dispute_core_stream_lambda_log_group_name" {
  value       = module.dispute_core_dynamodb.stream_lambda_cloudwatch_log_group_name
  description = "CloudWatch log group for dispute-core-ddb-stream (7-day retention)."
}

output "dispute_core_cdc_kinesis_stream_arn" {
  value       = module.dispute_core_dynamodb.cdc_kinesis_stream_arn
  description = "Kinesis stream ARN for DisputeCore CDC when datalake bucket is set."
}

output "dispute_core_cdc_firehose_arn" {
  value       = module.dispute_core_dynamodb.cdc_firehose_delivery_stream_arn
  description = "Firehose delivery stream ARN for DisputeCore CDC when configured."
}

output "dispute_event_bus_name" {
  value       = module.dispute_event_bus.event_bus_name
  description = "Disputes custom EventBridge bus name."
}

output "dispute_event_bus_arn" {
  value       = module.dispute_event_bus.event_bus_arn
  description = "Disputes custom EventBridge bus ARN."
}

output "dispute_event_bus_rule_arns" {
  value       = module.dispute_event_bus.rule_arns
  description = "EventBridge rule ARNs on dispute-event-bus."
}

output "dispute_event_bus_archive_arn" {
  value       = module.dispute_event_bus.event_archive_arn
  description = "EventBridge archive ARN for dispute-event-bus (full-bus retention: 30 days in prod)."
}

output "dispute_event_bus_log_group_name" {
  value       = module.dispute_event_bus.event_bus_log_group_name
  description = "CloudWatch log group for dispute-event-bus INFO logs (7-day retention)."
}

output "dispute_agent_fifo_queue_name" {
  value       = module.dispute_agent_fifo.queue_name
  description = "FIFO queue for disputes-core-invokeAgenticAI (name ends in .fifo)."
}

output "dispute_agent_fifo_queue_arn" {
  value       = module.dispute_agent_fifo.queue_arn
  description = "FIFO queue ARN for agentic AI events."
}

output "dispute_agent_fifo_queue_url" {
  value       = module.dispute_agent_fifo.queue_url
  description = "FIFO queue URL for agentic AI events."
}

output "dispute_agent_fifo_dlq_name" {
  value       = module.dispute_agent_fifo.dlq_name
  description = "FIFO DLQ for failed agentic AI messages (e.g. dispute-agent-dlq.fifo)."
}

output "dispute_agent_fifo_dlq_arn" {
  value       = module.dispute_agent_fifo.dlq_arn
  description = "FIFO DLQ ARN."
}

output "dispute_agent_fifo_dlq_url" {
  value       = module.dispute_agent_fifo.dlq_url
  description = "FIFO DLQ URL."
}

output "dispute_analysis_lambda_function_name" {
  value       = module.dispute_analysis_lambda.function_name
  description = "Dual-LLM dispute analysis Lambda name."
}

output "dispute_analysis_lambda_arn" {
  value       = module.dispute_analysis_lambda.function_arn
  description = "Analysis Lambda ARN when created by Terraform."
}

output "dispute_analysis_lambda_execution_role_arn" {
  value       = module.dispute_analysis_lambda.execution_role_arn
  description = "IAM role ARN for analysis Lambda (for reference / optional create-function in CI)."
}

output "dispute_analysis_lambda_log_group_name" {
  value       = module.dispute_analysis_lambda.cloudwatch_log_group_name
  description = "CloudWatch log group for dispute-agent-analysis (7-day retention)."
}

output "dispute_judgment_lambda_function_name" {
  value       = module.dispute_judgment_lambda.function_name
  description = "Batch judgment Lambda name."
}

output "dispute_judgment_lambda_arn" {
  value       = module.dispute_judgment_lambda.function_arn
  description = "Batch judgment Lambda ARN when created by Terraform."
}

output "dispute_judgment_lambda_schedule_rule_name" {
  value       = module.dispute_judgment_lambda.schedule_rule_name
  description = "Scheduled judgment EventBridge rule (default every 2 hours)."
}

output "dispute_judgment_lambda_log_group_name" {
  value       = module.dispute_judgment_lambda.cloudwatch_log_group_name
  description = "CloudWatch log group for dispute-agent-judgment (7-day retention)."
}
