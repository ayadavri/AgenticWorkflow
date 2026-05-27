aws_region     = "us-east-1"
aws_profile    = "dev-session"
aws_account_id = "302010998259"

tags = {
  Environment = "non-prod"
}

ri_core_base_url = "https://test-ri-core.residentinterface.com"

# DisputeCore table + stream
dynamodb_table_name                      = "DisputeCore"
dynamodb_stream_enabled                  = true
dispute_core_stream_lambda_function_name = "dispute-core-ddb-stream"

# CDC → datalake (Kinesis + Firehose)
dispute_core_firehose_s3_bucket = "dms-datalake-test-8c0e34"

# EventBridge dispute-event-bus → platform FIFO queues
dispute_event_bus_opensearch_target_sqs_arn = "arn:aws:sqs:us-east-1:302010998259:projections.fifo"
dispute_event_bus_temporal_target_sqs_arn   = "arn:aws:sqs:us-east-1:302010998259:workflow.fifo"

# disputes-core-invokeAgenticAI → dispute-agent.fifo → dispute-agent-analysis (900s Lambda)
dispute_agent_fifo_visibility_timeout_seconds = 300
dispute_analysis_lambda_attach_sqs            = true

# Judgment Lambda: EventBridge schedule enabled (see dispute_judgment_lambda_schedule_expression)
dispute_judgment_lambda_enable_daily_schedule = true
