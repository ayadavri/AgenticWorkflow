output "table_name" {
  value       = aws_dynamodb_table.dispute_core.name
  description = "DynamoDB table name."
}

output "table_arn" {
  value       = aws_dynamodb_table.dispute_core.arn
  description = "DynamoDB table ARN."
}

output "table_id" {
  value       = aws_dynamodb_table.dispute_core.id
  description = "DynamoDB table ID (same as name for standard tables)."
}

output "stream_arn" {
  value       = var.stream_enabled ? aws_dynamodb_table.dispute_core.stream_arn : null
  description = "DynamoDB stream ARN when stream_enabled is true."
}

output "stream_lambda_function_name" {
  value = length(aws_lambda_function.ddb_stream_bootstrap) > 0 ? aws_lambda_function.ddb_stream_bootstrap[0].function_name : (
    var.stream_lambda_function_name != "" ? var.stream_lambda_function_name : null
  )
  description = "Lambda subscribed to or intended for the table stream."
}

output "stream_lambda_arn" {
  value       = length(aws_lambda_function.ddb_stream_bootstrap) > 0 ? aws_lambda_function.ddb_stream_bootstrap[0].arn : null
  description = "ARN of the module-created bootstrap Lambda, if any."
}

output "stream_lambda_event_source_mapping_uuid" {
  value       = length(aws_lambda_event_source_mapping.stream_lambda) > 0 ? aws_lambda_event_source_mapping.stream_lambda[0].uuid : null
  description = "UUID of the Lambda event source mapping when attach_stream_lambda is true."
}

output "stream_lambda_cloudwatch_log_group_name" {
  value       = length(aws_cloudwatch_log_group.ddb_stream_lambda) > 0 ? aws_cloudwatch_log_group.ddb_stream_lambda[0].name : null
  description = "CloudWatch log group for the DisputeCore stream Lambda."
}

output "stream_lambda_cloudwatch_log_group_arn" {
  value       = length(aws_cloudwatch_log_group.ddb_stream_lambda) > 0 ? aws_cloudwatch_log_group.ddb_stream_lambda[0].arn : null
  description = "CloudWatch log group ARN for the DisputeCore stream Lambda."
}

output "cdc_kinesis_stream_name" {
  value       = local.cdc_to_datalake_enabled ? aws_kinesis_stream.dispute_core_cdc[0].name : null
  description = "Kinesis Data Stream receiving DynamoDB CDC when datalake bucket is configured."
}

output "cdc_kinesis_stream_arn" {
  value       = local.cdc_to_datalake_enabled ? aws_kinesis_stream.dispute_core_cdc[0].arn : null
  description = "ARN of CDC Kinesis stream when datalake bucket is configured."
}

output "cdc_firehose_delivery_stream_arn" {
  value       = local.cdc_to_datalake_enabled ? aws_kinesis_firehose_delivery_stream.dispute_core_cdc[0].arn : null
  description = "ARN of Firehose stream writing CDC to S3 when configured."
}

output "cdc_firehose_delivery_stream_name" {
  value       = local.cdc_to_datalake_enabled ? aws_kinesis_firehose_delivery_stream.dispute_core_cdc[0].name : null
  description = "Name of Firehose delivery stream when configured."
}

output "cdc_datalake_s3_bucket_used" {
  value       = local.cdc_to_datalake_enabled ? var.firehose_destination_s3_bucket_name : null
  description = "S3 bucket name used as Firehose destination when CDC pipeline is enabled."
}
