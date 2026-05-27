variable "table_name" {
  type        = string
  description = "DynamoDB table name."
  default     = "DisputeCore"
}

variable "billing_mode" {
  type        = string
  description = "PAY_PER_REQUEST or PROVISIONED."
  default     = "PAY_PER_REQUEST"
}

variable "hash_key" {
  type        = string
  description = "Table partition key attribute name."
  default     = "PK"
}

variable "range_key" {
  type        = string
  description = "Table sort key attribute name."
  default     = "SK"
}

variable "attributes" {
  type = list(object({
    name = string
    type = string
  }))
  description = "Attribute definitions for the table and indexes."
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

variable "global_secondary_indexes" {
  type = list(object({
    name            = string
    hash_key        = string
    range_key       = string
    projection_type = string
  }))
  description = "Global secondary index definitions."
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

variable "stream_enabled" {
  type        = bool
  description = "Enable DynamoDB Streams on the table."
  default     = false
}

variable "stream_view_type" {
  type        = string
  description = "Stream view type when stream_enabled is true."
  default     = "NEW_AND_OLD_IMAGES"
}

variable "stream_lambda_function_name" {
  type        = string
  description = "Lambda name to create (bootstrap stub) when create_stream_lambda is true; otherwise name/ARN of an existing function for aws_lambda_event_source_mapping only."
  default     = ""
}

variable "create_stream_lambda" {
  type        = bool
  description = "When true with streams + attach_stream_lambda: create IAM role, minimal Lambda (placeholder zip), and event source mapping. Set false only if subscribing to an already-provisioned function."
  default     = true
}

variable "attach_stream_lambda" {
  type        = bool
  description = "When true (and streams are enabled), create aws_lambda_event_source_mapping."
  default     = true
}

variable "stream_lambda_runtime" {
  type        = string
  description = "Lambda runtime when create_stream_lambda is true."
  default     = "nodejs20.x"
}

variable "stream_lambda_timeout_seconds" {
  type        = number
  description = "Lambda timeout when create_stream_lambda is true."
  default     = 60
}

variable "stream_lambda_memory_size" {
  type        = number
  description = "Lambda memory (MB) when create_stream_lambda is true."
  default     = 256
}

variable "stream_lambda_starting_position" {
  type        = string
  description = "Starting position for a new event source mapping (LATEST, TRIM_HORIZON). Ignored when updating an existing mapping."
  default     = "LATEST"
}

variable "stream_lambda_batch_size" {
  type        = number
  description = "Max records per invocation from the stream."
  default     = 100
}

variable "stream_lambda_maximum_batching_window_in_seconds" {
  type        = number
  description = "Maximum batching window for the stream event source mapping."
  default     = 0
}

variable "stream_lambda_environment_extra" {
  type        = map(string)
  description = "Additional or override environment variables for the bootstrap stream Lambda (merged on top of dispute-core defaults)."
  default     = {}
}

variable "stream_lambda_handler" {
  type        = string
  description = "Lambda handler: index.handler requires index.js at zip root (CI flattens dist/dispute-core-stream into the deployment zip)."
  default     = "index.handler"
}

variable "stream_lambda_log_retention_in_days" {
  type        = number
  description = "CloudWatch Logs retention for /aws/lambda/<stream_lambda_function_name>."
  default     = 7
}

variable "disputes_event_bus_name" {
  type        = string
  description = "Custom EventBridge bus for DISPUTES_EVENT_BUS_NAME and events:PutEvents IAM."
  default     = "dispute-event-bus"
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to the table."
  default     = {}
}

# --- DynamoDB CDC → Kinesis → Firehose → S3 (optional; enable by setting firehose_destination_s3_bucket_name) ---

variable "firehose_destination_s3_bucket_name" {
  type        = string
  description = "Existing S3 bucket for Firehose extended S3 delivery (e.g. datalake). Leave empty to skip Kinesis/Firehose."
  default     = ""
}

variable "dispute_core_cdc_kinesis_stream_name" {
  type        = string
  description = "Kinesis Data Stream name for DynamoDB CDC from this table."
  default     = "dispute-core-cdc"
}

variable "dispute_core_cdc_kinesis_shard_count" {
  type        = number
  description = "Shard count for the CDC Kinesis stream (provisioned mode)."
  default     = 1
}

variable "dispute_core_cdc_kinesis_retention_hours" {
  type        = number
  description = "Kinesis stream data retention in hours (24–8760)."
  default     = 168
}

variable "firehose_s3_prefix" {
  type        = string
  description = "S3 prefix for successful Firehose deliveries; supports expressions e.g. !{timestamp:yyyy/MM/dd/HH}/ (no leading slash)."
  default     = "dynamodb/cdc/disputecore/!{timestamp:yyyy/MM/dd/HH}/"
}

variable "firehose_s3_error_output_prefix" {
  type        = string
  description = "S3 prefix for delivery errors; supports Firehose dynamic expressions (e.g. !{firehose:error-output-type})."
  default     = "dynamodb/cdc/disputecore/errors/!{firehose:error-output-type}/!{timestamp:yyyy/MM/dd/HH}/"
}

variable "firehose_buffer_interval_seconds" {
  type        = number
  description = "Firehose extended S3 buffering interval (60–900 for Kinesis source)."
  default     = 300
}

variable "firehose_buffer_size_mb" {
  type        = number
  description = "Firehose extended S3 buffering size in MB (1–128)."
  default     = 5
}

variable "firehose_compression_format" {
  type        = string
  description = "UNCOMPRESSED, GZIP, ZIP, Snappy, or HADOOP_SNAPPY. Use UNCOMPRESSED with firehose_s3_file_extension=.json so S3 objects are plain JSON lines; GZIP yields compressed bytes (prefer a suffix like .json.gz if you keep compression)."
  default     = "UNCOMPRESSED"
}

variable "firehose_s3_file_extension" {
  type        = string
  description = "S3 object suffix for successful deliveries (must start with a period), e.g. .json."
  default     = ".json"
}

variable "firehose_log_retention_days" {
  type        = number
  description = "CloudWatch log retention for Firehose delivery logs."
  default     = 14
}
