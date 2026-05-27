variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "aws_profile" {
  type        = string
  description = "AWS CLI profile for provider and backend (production)."
  default     = "prod-session"
}

variable "aws_account_id" {
  type        = string
  description = "Expected production AWS account ID. Terraform will refuse other accounts."
  default     = "302010998259"
}

variable "dynamodb_table_name" {
  type        = string
  description = "DynamoDB table name for Dispute Core data."
  default     = "DisputeCore"
}

variable "dynamodb_billing_mode" {
  type        = string
  description = "PAY_PER_REQUEST or PROVISIONED."
  default     = "PAY_PER_REQUEST"
}

variable "dynamodb_attributes" {
  type = list(object({
    name = string
    type = string
  }))
  description = "DynamoDB attribute definitions (table + indexes)."
  default = [
    { name = "PK", type = "S" },
    { name = "SK", type = "S" },
    { name = "GSI1PK", type = "S" },
    { name = "GSI1SK", type = "S" },
    { name = "GSI2PK", type = "S" },
    { name = "GSI2SK", type = "S" },
    { name = "GSI3PK", type = "S" },
    { name = "GSI3SK", type = "S" },
  ]
}

variable "dynamodb_stream_enabled" {
  type        = bool
  description = "Enable DynamoDB Streams on DisputeCore (required for the stream Lambda)."
  default     = true
}

variable "dynamodb_stream_view_type" {
  type        = string
  description = "DynamoDB stream view type when streams are enabled."
  default     = "NEW_AND_OLD_IMAGES"
}

variable "dispute_core_stream_lambda_function_name" {
  type        = string
  description = "Lambda name: bootstrap when dynamodb_create_stream_lambda is true; CI deploys stream-lambda to this function."
  default     = "dispute-core-ddb-stream"
}

variable "dynamodb_create_stream_lambda" {
  type        = bool
  description = "When true with streams attached, Terraform creates IAM + placeholder Lambda."
  default     = true
}

variable "dynamodb_attach_stream_lambda" {
  type        = bool
  description = "Create aws_lambda_event_source_mapping for dispute_core_stream_lambda_function_name."
  default     = true
}

variable "dispute_core_stream_lambda_environment_extra" {
  type        = map(string)
  description = "Extra stream Lambda env vars (merged over module defaults)."
  default     = {}
}

variable "dispute_core_firehose_s3_bucket" {
  type        = string
  description = "Production datalake bucket for DisputeCore CDC (Kinesis→Firehose). Empty string skips CDC pipeline."
  default     = ""
}

variable "dispute_core_cdc_kinesis_stream_name" {
  type        = string
  description = "Kinesis Data Stream name for DynamoDB Kinesis streaming destination."
  default     = "dispute-core-cdc"
}

variable "dispute_core_cdc_kinesis_shard_count" {
  type        = number
  description = "Shard count for the CDC Kinesis stream (provisioned)."
  default     = 1
}

variable "dispute_core_firehose_s3_prefix" {
  type        = string
  description = "S3 prefix for successful CDC records (Firehose time expressions allowed)."
  default     = "dynamodb/cdc/disputecore/!{timestamp:yyyy/MM/dd/HH}/"
}

variable "dispute_core_firehose_s3_error_output_prefix" {
  type        = string
  description = "S3 prefix pattern for Firehose delivery errors."
  default     = "dynamodb/cdc/disputecore/errors/!{firehose:error-output-type}/!{timestamp:yyyy/MM/dd/HH}/"
}

variable "dynamodb_global_secondary_indexes" {
  type = list(object({
    name            = string
    hash_key        = string
    range_key       = string
    projection_type = string
  }))
  description = "DynamoDB global secondary indexes."
  default = [
    {
      name            = "GSI1"
      hash_key        = "GSI1PK"
      range_key       = "GSI1SK"
      projection_type = "ALL"
    },
    {
      name            = "GSI2"
      hash_key        = "GSI2PK"
      range_key       = "GSI2SK"
      projection_type = "ALL"
    },
    {
      name            = "GSI3"
      hash_key        = "GSI3PK"
      range_key       = "GSI3SK"
      projection_type = "ALL"
    }
  ]
}

variable "dispute_event_bus_opensearch_target_sqs_arn" {
  type        = string
  description = "Production FIFO SQS queue for disputes-core-invokeOpensearch (projections.fifo)."
  default     = null
  nullable    = true
}

variable "dispute_event_bus_temporal_target_sqs_arn" {
  type        = string
  description = "Production FIFO SQS queue for disputes-core-invokeTemporal (workflow.fifo)."
  default     = null
  nullable    = true
}

locals {
  dispute_event_bus_opensearch_target_sqs_arn = coalesce(
    var.dispute_event_bus_opensearch_target_sqs_arn,
    "arn:aws:sqs:${var.aws_region}:${var.aws_account_id}:projections.fifo",
  )
  dispute_event_bus_temporal_target_sqs_arn = coalesce(
    var.dispute_event_bus_temporal_target_sqs_arn,
    "arn:aws:sqs:${var.aws_region}:${var.aws_account_id}:workflow.fifo",
  )
}

variable "dispute_agent_fifo_queue_name" {
  type        = string
  description = "FIFO queue name for agentic AI EventBridge rule (must end with .fifo)."
  default     = "dispute-agent.fifo"
}

variable "dispute_agent_fifo_visibility_timeout_seconds" {
  type        = number
  description = "SQS visibility timeout (seconds). Should be >= dispute-agent-analysis Lambda timeout."
  default     = 300
}

variable "dispute_agent_fifo_redrive_max_receive_count" {
  type        = number
  description = "Primary queue receives before message is sent to dispute-agent-dlq.fifo. Set null to disable DLQ."
  default     = 3
  nullable    = true
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "ri_core_base_url" {
  type        = string
  description = "RI Core API base URL for dispute-agent-analysis and dispute-agent-judgment Lambda env (production)."
  default     = "https://prod-ri-core.residentinterface.com"
}

variable "dispute_analysis_lambda_function_name" {
  type        = string
  description = "Dual-LLM analysis Lambda; CI updates code via deploy-dispute-analysis-lambda-prod workflow."
  default     = "dispute-agent-analysis"
}

variable "dispute_analysis_lambda_create" {
  type        = bool
  description = "Create bootstrap analysis Lambda + IAM (placeholder zip; real code from GitHub Actions)."
  default     = true
}

variable "dispute_analysis_lambda_attach_stream" {
  type        = bool
  description = "Attach DisputeCore stream to analysis Lambda (second consumer alongside dispute-core-ddb-stream)."
  default     = false
}

variable "dispute_analysis_lambda_attach_sqs" {
  type        = bool
  description = "Attach dispute-agent.fifo (EventBridge agentic AI → SQS) to dispute-agent-analysis Lambda."
  default     = true
}

variable "dispute_analysis_lambda_environment_extra" {
  type        = map(string)
  description = "Non-secret env vars merged after defaults (overrides RI_CORE_BASE_URL when set)."
  default     = {}
}

variable "dispute_analysis_lambda_s3_bucket_names" {
  type        = list(string)
  description = "S3 buckets for analysis staging (GetObject, PutObject, ListBucket). Prod default uses -prod suffix (global S3 namespace)."
  default     = ["case-dispute-analysis-prod"]
}

variable "create_case_dispute_analysis_s3_bucket" {
  type        = bool
  description = "When true, create dispute_analysis_lambda_s3_bucket_names[0] plus encryption and public-access block (see s3_analysis_lambda_access.tf). Prod defaults to true (greenfield); set false if the bucket already exists."
  default     = true
}

variable "dispute_analysis_lambda_s3_read_bucket_names" {
  type        = list(string)
  description = "S3 buckets read-only for analysis Lambda (source dispute PDFs before CopyObject to staging)."
  default     = ["resident-documents-f2850309"]
}

variable "dispute_analysis_lambda_ssm_parameter_names" {
  type        = list(string)
  description = "SSM parameter path segments after 'parameter/' (no leading slash), e.g. agents/OPENAI_KEY for /agents/OPENAI_KEY."
  default = [
    "agents/OPENAI_KEY",
    "agents/ENCRYPTION_KEY",
    "agents/COLLECTION_CORE_DOCUMENTS_API_KEY",
  ]
}

variable "dispute_judgment_lambda_function_name" {
  type    = string
  default = "dispute-agent-judgment"
}

variable "dispute_judgment_lambda_create" {
  type    = bool
  default = true
}

variable "dispute_judgment_lambda_enable_daily_schedule" {
  type        = bool
  description = "EventBridge schedule for batch judgment Lambda off in prod until enabled intentionally."
  default     = false
}

variable "dispute_judgment_lambda_schedule_expression" {
  type        = string
  description = "EventBridge schedule (UTC). Default rate(2 hours); use cron(30 3 * * ? *) for daily 09:00 IST."
  default     = "rate(2 hours)"
}

variable "dispute_judgment_lambda_environment_extra" {
  type    = map(string)
  default = {}
}

variable "dispute_judgment_lambda_s3_bucket_names" {
  type        = list(string)
  description = "Judgment Lambda S3 access; align with analysis staging bucket."
  default     = ["case-dispute-analysis-prod"]
}

variable "dispute_judgment_lambda_ssm_parameter_names" {
  type        = list(string)
  description = "SSM parameter paths (same convention as dispute_analysis_lambda_ssm_parameter_names)."
  default     = ["agents/OPENAI_KEY", "agents/ENCRYPTION_KEY"]
}
