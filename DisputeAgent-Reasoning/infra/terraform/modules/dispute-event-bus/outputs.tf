output "event_bus_name" {
  value       = aws_cloudwatch_event_bus.dispute.name
  description = "Custom EventBridge bus name."
}

output "event_bus_arn" {
  value       = aws_cloudwatch_event_bus.dispute.arn
  description = "ARN of the dispute event bus."
}

output "event_bus_log_group_name" {
  value       = aws_cloudwatch_log_group.event_bus.name
  description = "CloudWatch log group for EventBridge bus INFO logs (retention configured in Terraform)."
}

output "rule_names" {
  value       = { for k, r in aws_cloudwatch_event_rule.dispute_route : k => r.name }
  description = "Event rule names keyed by logical rule key."
}

output "rule_arns" {
  value       = { for k, r in aws_cloudwatch_event_rule.dispute_route : k => r.arn }
  description = "Event rule ARNs keyed by logical rule key."
}

output "event_archive_arn" {
  value       = aws_cloudwatch_event_archive.dispute.arn
  description = "EventBridge archive ARN for the dispute-event-bus archive."
}
