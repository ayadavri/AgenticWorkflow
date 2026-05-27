locals {
  event_bus_name           = "dispute-event-bus"
  event_bus_log_group_name = "/aws/events/${local.event_bus_name}"
  event_source             = "com.residentinterface.disputes"

  dispute_event_rules = {
    agentic_ai = {
      rule_name = "disputes-core-invokeAgenticAI"
      detail_types = [
        "disputes.case.created.agentic",
      ]
    }
    opensearch = {
      rule_name = "disputes-core-invokeOpensearch"
      detail_types = [
        "disputes.case.created.ready-for-index",
        "disputes.case.updated.ready-for-index",
        "disputes.case.removed.ready-for-index",
      ]
    }
    temporal = {
      rule_name = "disputes-core-invokeTemporal"
      detail_types = [
        "disputes.case.created",
        "disputes.case.updated",
        "disputes.case.removed",
      ]
    }
    data_warehouse = {
      rule_name = "disputes-core-invokeDataWarehouse"
      detail_types = [
        "disputes.case.created.data-warehouse",
        "disputes.case.updated.data-warehouse",
        "disputes.case.removed.data-warehouse",
      ]
    }
  }
}

resource "aws_cloudwatch_log_group" "event_bus" {
  name              = local.event_bus_log_group_name
  retention_in_days = var.log_retention_in_days

  tags = merge(var.tags, { Purpose = "dispute-event-bus-logs" })
}

resource "aws_cloudwatch_event_bus" "dispute" {
  name = local.event_bus_name
  tags = var.tags

  # Event bus logging → CloudWatch Logs (log group above).
  log_config {
    level          = "INFO"
    include_detail = "NONE"
  }

  depends_on = [aws_cloudwatch_log_group.event_bus]
}

# Full-bus archive for replay/debug (retention_days configured per environment in deployment TF).
resource "aws_cloudwatch_event_archive" "dispute" {
  name             = "${local.event_bus_name}-archive"
  description      = "Archive all events published to ${local.event_bus_name}."
  event_source_arn = aws_cloudwatch_event_bus.dispute.arn
  retention_days   = var.event_archive_retention_days
}

resource "aws_cloudwatch_event_rule" "dispute_route" {
  for_each = local.dispute_event_rules

  name           = each.value.rule_name
  description    = "Match ${join(", ", each.value.detail_types)}"
  event_bus_name = aws_cloudwatch_event_bus.dispute.name

  event_pattern = jsonencode({
    "detail-type" = each.value.detail_types
    source        = [local.event_source]
  })
}

# SQS queues must grant events.amazonaws.com sqs:SendMessage for the matching rule ARN
# (see non-prod aws_sqs_queue_policy.dispute_agent_fifo_eventbridge for the agentic FIFO).

resource "aws_cloudwatch_event_target" "opensearch_sqs" {
  event_bus_name = aws_cloudwatch_event_bus.dispute.name
  rule           = aws_cloudwatch_event_rule.dispute_route["opensearch"].name
  arn            = var.opensearch_rule_sqs_target_arn

  sqs_target {
    message_group_id = var.event_fifo_sqs_message_group_id
  }
}

resource "aws_cloudwatch_event_target" "temporal_sqs" {
  event_bus_name = aws_cloudwatch_event_bus.dispute.name
  rule           = aws_cloudwatch_event_rule.dispute_route["temporal"].name
  arn            = var.temporal_rule_sqs_target_arn

  sqs_target {
    message_group_id = var.event_fifo_sqs_message_group_id
  }
}

resource "aws_cloudwatch_event_target" "agentic_ai_sqs" {
  count = var.agentic_ai_rule_sqs_target_enabled ? 1 : 0

  event_bus_name = aws_cloudwatch_event_bus.dispute.name
  rule           = aws_cloudwatch_event_rule.dispute_route["agentic_ai"].name
  arn            = var.agentic_ai_rule_sqs_target_arn

  sqs_target {
    message_group_id = var.event_fifo_sqs_message_group_id
  }
}
