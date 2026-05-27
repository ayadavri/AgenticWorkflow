variable "tags" {
  type        = map(string)
  description = "Tags applied to the event bus."
  default     = {}
}

variable "log_retention_in_days" {
  type        = number
  description = "CloudWatch Logs retention for /aws/events/<event-bus-name> (EventBridge bus INFO logs)."
  default     = 7
}

variable "event_archive_retention_days" {
  type        = number
  description = "EventBridge archive retention for all events on the dispute bus (replay/audit)."
}

variable "opensearch_rule_sqs_target_arn" {
  type        = string
  description = "FIFO SQS queue ARN targeted by disputes-core-invokeOpensearch rule."
}

variable "temporal_rule_sqs_target_arn" {
  type        = string
  description = "FIFO SQS queue ARN targeted by disputes-core-invokeTemporal rule."
}

variable "agentic_ai_rule_sqs_target_arn" {
  type        = string
  description = "FIFO SQS queue ARN for disputes-core-invokeAgenticAI. Used when agentic_ai_rule_sqs_target_enabled is true."
  default     = ""
}

variable "agentic_ai_rule_sqs_target_enabled" {
  type        = bool
  description = "When true, create the EventBridge SQS target. Use this flag (not the ARN) for count — ARN may be unknown until apply when it comes from another module."
  default     = false
}

variable "event_fifo_sqs_message_group_id" {
  type        = string
  description = "MessageGroupId for EventBridge deliveries to FIFO SQS targets."
  default     = "dispute-events"
}
