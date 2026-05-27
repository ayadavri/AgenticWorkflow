data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  create   = var.create_lambda
  schedule = local.create && var.enable_daily_schedule

  # Same baseline as dispute-analysis Lambda; merge last so callers can override.
  default_environment_variables = {
    ANALYSIS_MODEL                       = "gpt-5.5-2026-04-23"
    ANALYSIS_MODEL_MAX_TOKENS            = "1000"
    ANALYSIS_MODEL_TEMPERATURE           = "0.0"
    ANALYSIS_MODEL_API_KEY_SSM_PARAMETER = "/agents/OPENAI_KEY"
    JUDGMENT_MODEL                       = "gpt-5.5-2026-04-23"
    JUDGMENT_MODEL_MAX_TOKENS            = "1000"
    JUDGMENT_MODEL_TEMPERATURE           = "0.0"
    JUDGMENT_MODEL_API_KEY_SSM_PARAMETER = "/agents/OPENAI_KEY"
    DYNAMO_DB_MAX_RETRY                  = "5"
    CONNECT_TIMEOUT                      = "5"
    READ_TIMEOUT                         = "60"
    BASE_DELAY_SECONDS                   = "0.5"
    MAX_DELAY_SECONDS                    = "8.0"
    RI_CORE_BASE_URL                     = "https://test-ri-core.residentinterface.com"
    RI_CORE_HTTP_TIMEOUT_S               = "30.0"
    CONFIG_S3_BUCKET                     = "case-dispute-analysis"
    CONFIG_S3_PREFIX                     = "configuration/"
    CONFIG_JSON_FILES                    = "[\"originatorDisputeCode1.json\", \"originatorDisputeCode2.json\"]"
    SOURCE_LIST                          = "[\"eoscar\"]"
    ENABLE_AI_REVIEW                     = "False"
    CASE_DISPUTE_ANALYSIS_S3_BUCKET      = "case-dispute-analysis"
    CASE_DISPUTE_ANALYSIS_S3_PREFIX      = "input/"
    ENCRYPTION_KEY_SSM_PARAMETER         = "/agents/ENCRYPTION_KEY"
    CONFIDENCE_CHECK_ENABLED             = "False"
    AI_CONFIDENCE_LEVEL_THRESHOLD        = "100"
  }

  merged_environment_variables = merge(local.default_environment_variables, var.environment_variables)

  schedule_rule_name = coalesce(
    var.schedule_rule_name,
    "${var.function_name}-every-2h",
  )

  s3_object_arns = [
    for arn in var.s3_bucket_arns :
    endswith(arn, "/*") ? arn : "${arn}/*"
  ]
}

data "aws_iam_policy_document" "assume" {
  count = local.create ? 1 : 0

  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "archive_file" "bootstrap_zip" {
  count = local.create ? 1 : 0

  type        = "zip"
  output_path = "${path.module}/.generated/judgment-lambda-bootstrap-${replace(var.function_name, "/", "_")}.zip"

  source {
    filename = "disput_judgment_lambda_handler.py"
    content  = <<-EOT
      def batch_judgment_stream_event_handler(event, context):
          return {"processed": 0, "bootstrap": True}
    EOT
  }
}

resource "aws_iam_role" "judgment_execution" {
  count = local.create ? 1 : 0

  name               = substr("${var.function_name}-exec", 0, 64)
  assume_role_policy = data.aws_iam_policy_document.assume[0].json
  tags               = merge(var.tags, { Role = "dispute-agent-judgment" })
}

resource "aws_iam_role_policy_attachment" "basic_execution" {
  count = local.create ? 1 : 0

  role       = aws_iam_role.judgment_execution[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "dynamodb" {
  count = local.create && var.dispute_core_table_arn != "" ? 1 : 0

  name = "dispute-core-dynamodb"
  role = aws_iam_role.judgment_execution[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:Query",
          "dynamodb:BatchWriteItem",
          "dynamodb:ConditionCheckItem",
        ]
        Resource = [
          var.dispute_core_table_arn,
          "${var.dispute_core_table_arn}/index/*",
        ]
      },
    ]
  })
}

resource "aws_iam_role_policy" "s3" {
  count = local.create && length(local.s3_object_arns) > 0 ? 1 : 0

  name = "dispute-judgment-s3"
  role = aws_iam_role.judgment_execution[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket",
        ]
        Resource = local.s3_object_arns
      },
    ]
  })
}

resource "aws_iam_role_policy" "ssm" {
  count = local.create && length(var.ssm_parameter_arns) > 0 ? 1 : 0

  name = "dispute-judgment-ssm"
  role = aws_iam_role.judgment_execution[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:GetParameters"]
        Resource = var.ssm_parameter_arns
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "judgment" {
  count = local.create ? 1 : 0

  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = var.log_retention_in_days

  tags = merge(var.tags, { Purpose = "dispute-agent-judgment-logs" })
}

resource "aws_lambda_function" "judgment" {
  count = local.create ? 1 : 0

  function_name = var.function_name
  description   = "Batch judgment workflow (bootstrap placeholder; code deployed via CI). Scheduled every 2 hours when enable_daily_schedule is true."
  role          = aws_iam_role.judgment_execution[0].arn

  runtime     = var.runtime
  handler     = var.handler
  timeout     = var.timeout_seconds
  memory_size = var.memory_size

  filename         = data.archive_file.bootstrap_zip[0].output_path
  source_code_hash = data.archive_file.bootstrap_zip[0].output_base64sha256

  environment {
    variables = local.merged_environment_variables
  }

  lifecycle {
    ignore_changes = [
      filename,
      source_code_hash,
    ]
  }

  tags = merge(var.tags, { Purpose = "dispute-agent-judgment-bootstrap" })

  depends_on = [
    aws_cloudwatch_log_group.judgment,
    aws_iam_role_policy_attachment.basic_execution,
  ]
}

resource "aws_cloudwatch_event_rule" "daily_judgment" {
  count = local.schedule ? 1 : 0

  name                = local.schedule_rule_name
  description         = "Invoke ${var.function_name} on schedule (${var.schedule_expression})."
  schedule_expression = var.schedule_expression

  tags = merge(var.tags, { Purpose = "dispute-agent-judgment-every-2h-schedule" })
}

resource "aws_cloudwatch_event_target" "daily_judgment" {
  count = local.schedule ? 1 : 0

  rule      = aws_cloudwatch_event_rule.daily_judgment[0].name
  target_id = "judgment-lambda"
  arn       = aws_lambda_function.judgment[0].arn

  input = jsonencode({
    source  = "scheduled"
    trigger = "scheduled-every-2h"
  })
}

resource "aws_lambda_permission" "allow_eventbridge_schedule" {
  count = local.schedule ? 1 : 0

  statement_id  = "AllowExecutionFromEventBridgeDailyJudgment"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.judgment[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_judgment[0].arn
}
