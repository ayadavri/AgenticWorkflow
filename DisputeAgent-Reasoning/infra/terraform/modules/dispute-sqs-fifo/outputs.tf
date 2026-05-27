output "queue_id" {
  value       = aws_sqs_queue.fifo.id
  description = "SQS queue URL (same as id)."
}

output "queue_arn" {
  value       = aws_sqs_queue.fifo.arn
  description = "SQS queue ARN."
}

output "queue_name" {
  value       = aws_sqs_queue.fifo.name
  description = "FIFO queue name."
}

output "queue_url" {
  value       = aws_sqs_queue.fifo.url
  description = "SQS queue URL."
}

output "dlq_arn" {
  value       = length(aws_sqs_queue.dlq) > 0 ? aws_sqs_queue.dlq[0].arn : null
  description = "FIFO DLQ ARN when redrive_max_receive_count is set."
}

output "dlq_name" {
  value       = length(aws_sqs_queue.dlq) > 0 ? aws_sqs_queue.dlq[0].name : null
  description = "FIFO DLQ name when configured."
}

output "dlq_url" {
  value       = length(aws_sqs_queue.dlq) > 0 ? aws_sqs_queue.dlq[0].url : null
  description = "FIFO DLQ URL when configured."
}
