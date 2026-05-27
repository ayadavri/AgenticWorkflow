variable "function_name" {
  type        = string
  description = "Lambda function name (CI deploy-dispute-analysis-lambda-* workflows update this function)."
  default     = "dispute-agent-analysis"
}

variable "create_lambda" {
  type        = bool
  description = "When true, create IAM role + bootstrap placeholder Lambda (real code deployed via GitHub Actions)."
  default     = true
}

variable "handler" {
  type        = string
  description = "Lambda handler; must match zip layout after CI deploy (handler module at zip root)."
  default     = "disput_analysis_lambda_handler.dynamo_stream_event_handler"
}

variable "runtime" {
  type    = string
  default = "python3.11"
}

variable "timeout_seconds" {
  type        = number
  description = "Lambda timeout; dual-LLM runs need a high value (max 900)."
  default     = 900
}

variable "memory_size" {
  type    = number
  default = 1024
}

variable "log_retention_in_days" {
  type        = number
  description = "CloudWatch Logs retention for /aws/lambda/<function_name>."
  default     = 7
}

variable "environment_variables" {
  type        = map(string)
  description = "Lambda environment variables merged after module defaults (non-secret config; use SSM for API keys). Later keys override defaults."
  default     = {}
}

variable "dispute_core_table_arn" {
  type        = string
  description = "DisputeCore DynamoDB table ARN for read/write IAM."
  default     = ""
}

variable "dispute_core_stream_arn" {
  type        = string
  description = "DisputeCore stream ARN; required when attach_stream_event_source is true."
  default     = ""
}

variable "attach_stream_event_source" {
  type        = bool
  description = "Attach a DynamoDB stream event source mapping (second consumer alongside dispute-core-ddb-stream)."
  default     = false
}

variable "stream_starting_position" {
  type    = string
  default = "LATEST"
}

variable "stream_batch_size" {
  type    = number
  default = 10
}

variable "stream_maximum_batching_window_in_seconds" {
  type    = number
  default = 0
}

variable "sqs_queue_arn" {
  type        = string
  description = "Optional FIFO queue ARN (e.g. dispute-agent.fifo) when attach_sqs_event_source is true."
  default     = ""
}

variable "attach_sqs_event_source" {
  type        = bool
  description = "Attach SQS event source mapping (EventBridge envelope in message body, e.g. dispute-agent.fifo)."
  default     = false
}

variable "sqs_batch_size" {
  type        = number
  description = "Max SQS messages per Lambda invocation when attach_sqs_event_source is true."
  default     = 5
}

variable "s3_bucket_arns" {
  type        = list(string)
  description = "S3 bucket ARNs for analysis staging (GetObject, ListBucket, PutObject on bucket and objects)."
  default     = []
}

variable "s3_read_only_bucket_arns" {
  type        = list(string)
  description = "S3 bucket ARNs for read-only access (e.g. resident dispute PDFs copied into analysis bucket)."
  default     = []
}

variable "ssm_parameter_arns" {
  type        = list(string)
  description = "SSM parameter ARNs for API keys and secrets (GetParameter)."
  default     = []
}

variable "tags" {
  type    = map(string)
  default = {}
}
