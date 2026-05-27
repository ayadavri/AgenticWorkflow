data "aws_caller_identity" "current" {}
data "aws_region" "current" {}


locals {
  attach_stream_mapping   = var.stream_enabled && var.attach_stream_lambda && var.stream_lambda_function_name != ""
  create_bootstrap_lambda = local.attach_stream_mapping && var.create_stream_lambda
  cdc_to_datalake_enabled = trimspace(var.firehose_destination_s3_bucket_name) != ""

  stream_lambda_environment_base = {
    DISPUTE_CORE_EVENTBRIDGE_ENABLED   = "true"
    EVENTBRIDGE_DEBUG                  = "true"
    DISPUTE_EVENTBRIDGE_SOURCE         = "com.residentinterface.disputes"
    DISPUTE_CORE_INVOKE_TEMPORAL       = "true"
    DISPUTE_CORE_INVOKE_OPENSEARCH     = "true"
    DISPUTE_CORE_INVOKE_DATA_WAREHOUSE = "true"
    DISPUTE_CORE_INVOKE_AGENTIC_AI     = "true"
    DISPUTES_EVENT_BUS_NAME            = var.disputes_event_bus_name
  }
  stream_lambda_environment = merge(local.stream_lambda_environment_base, var.stream_lambda_environment_extra)

  stream_lambda_log_group_enabled = trimspace(var.stream_lambda_function_name) != ""
}

resource "aws_dynamodb_table" "dispute_core" {
  name         = var.table_name
  billing_mode = var.billing_mode

  hash_key  = var.hash_key
  range_key = var.range_key

  stream_enabled   = var.stream_enabled
  stream_view_type = var.stream_enabled ? var.stream_view_type : null

  dynamic "attribute" {
    for_each = var.attributes
    content {
      name = attribute.value.name
      type = attribute.value.type
    }
  }

  dynamic "global_secondary_index" {
    for_each = var.global_secondary_indexes
    content {
      name = global_secondary_index.value.name

      key_schema {
        attribute_name = global_secondary_index.value.hash_key
        key_type       = "HASH"
      }

      key_schema {
        attribute_name = global_secondary_index.value.range_key
        key_type       = "RANGE"
      }

      projection_type = global_secondary_index.value.projection_type
    }
  }

  tags = var.tags
}

data "aws_iam_policy_document" "stream_lambda_assume" {
  count = local.create_bootstrap_lambda ? 1 : 0

  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "archive_file" "stream_lambda_bootstrap_zip" {
  count = local.create_bootstrap_lambda ? 1 : 0

  type        = "zip"
  output_path = "${path.module}/.generated/stream-lambda-bootstrap-${replace(var.stream_lambda_function_name, "/", "_")}.zip"

  source {
    # Minimal bootstrap: single file at zip root. Real stream-lambda layout + handler are deployed by CI.
    filename = "index.js"
    content  = <<-EOT
      'use strict';
      exports.handler = async () => ({ ok: true, bootstrap: true });
    EOT
  }
}

resource "aws_iam_role" "stream_lambda_execution" {
  count = local.create_bootstrap_lambda ? 1 : 0

  name               = substr("${var.stream_lambda_function_name}-exec", 0, 64)
  assume_role_policy = data.aws_iam_policy_document.stream_lambda_assume[0].json
  tags               = merge(var.tags, { Role = "dispute-core-ddb-stream" })
}

resource "aws_iam_role_policy_attachment" "stream_lambda_basic_execution" {
  count = local.create_bootstrap_lambda ? 1 : 0

  role       = aws_iam_role.stream_lambda_execution[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "stream_lambda_dynamo_stream_read" {
  count = local.create_bootstrap_lambda ? 1 : 0

  name = "ddb-stream-read"
  role = aws_iam_role.stream_lambda_execution[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetRecords",
          "dynamodb:GetShardIterator",
          "dynamodb:DescribeStream",
          "dynamodb:ListShards",
        ]
        Resource = aws_dynamodb_table.dispute_core.stream_arn
      },
    ]
  })
}

resource "aws_iam_role_policy" "stream_lambda_eventbridge_put" {
  count = local.create_bootstrap_lambda ? 1 : 0

  name = "eventbridge-put-events-disputes-bus"
  role = aws_iam_role.stream_lambda_execution[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["events:PutEvents"]
        Resource = "arn:aws:events:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:event-bus/${var.disputes_event_bus_name}"
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "ddb_stream_lambda" {
  count = local.stream_lambda_log_group_enabled ? 1 : 0

  name              = "/aws/lambda/${var.stream_lambda_function_name}"
  retention_in_days = var.stream_lambda_log_retention_in_days

  tags = merge(var.tags, { Purpose = "dispute-core-ddb-stream-logs" })
}

resource "aws_lambda_function" "ddb_stream_bootstrap" {
  count = local.create_bootstrap_lambda ? 1 : 0

  function_name = var.stream_lambda_function_name
  description   = "DisputeCore table stream processor (bootstrap placeholder; code deployed via CI)."
  role          = aws_iam_role.stream_lambda_execution[0].arn

  runtime     = var.stream_lambda_runtime
  handler     = var.stream_lambda_handler
  timeout     = var.stream_lambda_timeout_seconds
  memory_size = var.stream_lambda_memory_size

  filename         = data.archive_file.stream_lambda_bootstrap_zip[0].output_path
  source_code_hash = data.archive_file.stream_lambda_bootstrap_zip[0].output_base64sha256

  environment {
    variables = local.stream_lambda_environment
  }

  lifecycle {
    # CI deploys zip (index.js at root); do not revert code or handler from apply.
    ignore_changes = [
      filename,
      source_code_hash,
    ]
  }

  tags = merge(var.tags, { Purpose = "dispute-core-ddb-stream-bootstrap" })

  depends_on = [
    aws_cloudwatch_log_group.ddb_stream_lambda,
    aws_iam_role_policy_attachment.stream_lambda_basic_execution,
    aws_iam_role_policy.stream_lambda_dynamo_stream_read,
    aws_iam_role_policy.stream_lambda_eventbridge_put,
  ]
}

resource "aws_lambda_event_source_mapping" "stream_lambda" {
  count = local.attach_stream_mapping ? 1 : 0

  event_source_arn  = aws_dynamodb_table.dispute_core.stream_arn
  function_name     = local.create_bootstrap_lambda ? aws_lambda_function.ddb_stream_bootstrap[0].function_name : var.stream_lambda_function_name
  starting_position = var.stream_lambda_starting_position

  batch_size                         = var.stream_lambda_batch_size
  maximum_batching_window_in_seconds = var.stream_lambda_maximum_batching_window_in_seconds
}
