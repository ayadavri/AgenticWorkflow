variable "function_name" {
  type        = string
  description = "Judgment batch Lambda; CI deploy workflow updates code."
  default     = "dispute-agent-judgment"
}

variable "create_lambda" {
  type        = bool
  description = "Create IAM role + bootstrap placeholder Lambda."
  default     = true
}

variable "handler" {
  type        = string
  default     = "disput_judgment_lambda_handler.batch_judgment_stream_event_handler"
}

variable "runtime" {
  type    = string
  default = "python3.11"
}

variable "timeout_seconds" {
  type        = number
  description = "Batch judgment may run many pending rows."
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
  description = "Non-secret Lambda env vars merged after module defaults; later keys override defaults."
  default     = {}
}

variable "dispute_core_table_arn" {
  type        = string
  description = "DisputeCore table ARN for DynamoDB IAM."
  default     = ""
}

variable "enable_daily_schedule" {
  type        = bool
  description = "When true, invoke this Lambda on schedule_expression."
  default     = true
}

variable "schedule_expression" {
  type        = string
  description = "EventBridge schedule (UTC). Default rate(2 hours) for initial rollout; use cron(30 3 * * ? *) for daily 09:00 IST later."
  default     = "rate(2 hours)"
}

variable "schedule_rule_name" {
  type        = string
  description = "CloudWatch Events rule name for the scheduled judgment run."
  default     = ""
}

variable "s3_bucket_arns" {
  type        = list(string)
  default     = []
}

variable "ssm_parameter_arns" {
  type        = list(string)
  default     = []
}

variable "tags" {
  type    = map(string)
  default = {}
}
