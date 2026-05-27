locals {
  dlq_enabled = var.redrive_max_receive_count != null && var.redrive_max_receive_count > 0
  dlq_name    = coalesce(var.dlq_name, "${trimsuffix(var.queue_name, ".fifo")}-dlq.fifo")
}

resource "aws_sqs_queue" "dlq" {
  count = local.dlq_enabled ? 1 : 0

  name       = local.dlq_name
  fifo_queue = true

  message_retention_seconds = var.dlq_message_retention_seconds

  content_based_deduplication = var.content_based_deduplication
  deduplication_scope         = var.deduplication_scope
  fifo_throughput_limit       = var.fifo_throughput_limit
  sqs_managed_sse_enabled     = true

  tags = merge(var.tags, { Purpose = "dispute-agent-fifo-dlq" })
}

resource "aws_sqs_queue" "fifo" {
  name       = var.queue_name
  fifo_queue = true

  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = var.message_retention_seconds
  receive_wait_time_seconds  = var.receive_wait_time_seconds

  content_based_deduplication = var.content_based_deduplication
  deduplication_scope         = var.deduplication_scope
  fifo_throughput_limit       = var.fifo_throughput_limit
  sqs_managed_sse_enabled     = true

  redrive_policy = local.dlq_enabled ? jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[0].arn
    maxReceiveCount     = var.redrive_max_receive_count
  }) : null

  tags = merge(var.tags, { Purpose = "dispute-agent-fifo" })

  depends_on = [aws_sqs_queue.dlq]
}
