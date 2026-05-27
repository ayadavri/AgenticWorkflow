variable "queue_name" {
  type        = string
  description = "FIFO queue name (must end with .fifo)."
}

variable "visibility_timeout_seconds" {
  type        = number
  description = "Visibility timeout for consumed messages. Must be >= attached Lambda timeout when used as an event source."
  default     = 300
}

variable "message_retention_seconds" {
  type    = number
  default = 345600
}

variable "receive_wait_time_seconds" {
  type        = number
  description = "Long polling wait time (0–20)."
  default     = 0
}

variable "content_based_deduplication" {
  type        = bool
  description = "Enable content-based deduplication for FIFO queues (recommended for EventBridge → SQS)."
  default     = true
}

variable "deduplication_scope" {
  type    = string
  default = "messageGroup"
}

variable "fifo_throughput_limit" {
  type    = string
  default = "perMessageGroupId"
}

variable "dlq_name" {
  type        = string
  description = "FIFO DLQ name (default: <queue_name without .fifo>-dlq.fifo, e.g. dispute-agent-dlq.fifo)."
  default     = null
  nullable    = true
}

variable "redrive_max_receive_count" {
  type        = number
  description = "Max receives on the primary queue before SQS moves the message to the DLQ. Set null to disable DLQ."
  default     = 3
  nullable    = true
}

variable "dlq_message_retention_seconds" {
  type        = number
  description = "DLQ message retention (default 14 days)."
  default     = 1209600
}

variable "tags" {
  type    = map(string)
  default = {}
}
