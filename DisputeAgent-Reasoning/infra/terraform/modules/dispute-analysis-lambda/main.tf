data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  create = var.create_lambda

  # Shared application defaults (non-secret); merge last so callers can override.
  default_environment_variables = {
    ANALYSIS_MODEL                       = "gpt-5.5-2026-04-23"
    ANALYSIS_MODEL_MAX_TOKENS            = "16384"
    ANALYSIS_MODEL_TEMPERATURE           = "0.0"
    ANALYSIS_MODEL_API_KEY_SSM_PARAMETER = "/agents/OPENAI_KEY"
    JUDGMENT_MODEL                       = "gpt-5.5-2026-04-23"
    JUDGMENT_MODEL_MAX_TOKENS            = "16384"
    JUDGMENT_MODEL_TEMPERATURE           = "0.0"
    JUDGMENT_MODEL_API_KEY_SSM_PARAMETER = "/agents/OPENAI_KEY"
    DYNAMO_DB_MAX_RETRY                  = "5"
    CONNECT_TIMEOUT                      = "5"
    READ_TIMEOUT                         = "60"
    BASE_DELAY_SECONDS                   = "0.5"
    MAX_DELAY_SECONDS                    = "8.0"
    RI_CORE_HTTP_TIMEOUT_S               = "30.0"
    CONFIG_S3_BUCKET                     = "case-dispute-analysis"
    CONFIG_S3_PREFIX                     = "configuration/"
    CONFIG_JSON_FILES                    = "[\"originatorDisputeCode1.json\", \"originatorDisputeCode2.json\"]"
    SOURCE_LIST                          = "[\"eoscar\"]"
    ENABLE_AI_REVIEW                     = "False"
    CASE_DISPUTE_ANALYSIS_S3_BUCKET      = "case-dispute-analysis"
    CASE_DISPUTE_ANALYSIS_S3_PREFIX      = "input/"
    ENCRYPTION_KEY_SSM_PARAMETER                  = "/agents/ENCRYPTION_KEY"
    COLLECTION_CORE_DOCUMENTS_API_SSM_PARAMETER   = "/agents/COLLECTION_CORE_DOCUMENTS_API_KEY"
    CONFIDENCE_CHECK_ENABLED                      = "False"
    AI_CONFIDENCE_LEVEL_THRESHOLD        = "100"
  }

  merged_environment_variables = merge(local.default_environment_variables, var.environment_variables)

  attach_stream = (
    local.create
    && var.attach_stream_event_source
    && var.dispute_core_stream_arn != ""
  )

  # Do not gate on sqs_queue_arn != "" — ARN is often (known after apply) from another
  # module, which makes this unknown and breaks count. When attach_sqs_event_source is
  # true, caller must supply a concrete queue ARN (same apply is fine).
  attach_sqs = local.create && var.attach_sqs_event_source

  s3_object_arns = [
    for arn in var.s3_bucket_arns :
    endswith(arn, "/*") ? arn : "${arn}/*"
  ]

  s3_read_only_object_arns = [
    for arn in var.s3_read_only_bucket_arns :
    endswith(arn, "/*") ? arn : "${arn}/*"
  ]

  s3_policy_enabled = local.create && (length(local.s3_object_arns) > 0 || length(local.s3_read_only_object_arns) > 0)
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
  output_path = "${path.module}/.generated/analysis-lambda-bootstrap-${replace(var.function_name, "/", "_")}.zip"

  source {
    filename = "disput_analysis_lambda_handler.py"
    content  = <<-EOT
      def dynamo_stream_event_handler(event, context):
          return {"processed": 0, "bootstrap": True}
    EOT
  }
}

resource "aws_iam_role" "analysis_execution" {
  count = local.create ? 1 : 0

  name               = substr("${var.function_name}-exec", 0, 64)
  assume_role_policy = data.aws_iam_policy_document.assume[0].json
  tags               = merge(var.tags, { Role = "dispute-agent-analysis" })
}

resource "aws_iam_role_policy_attachment" "basic_execution" {
  count = local.create ? 1 : 0

  role       = aws_iam_role.analysis_execution[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "dynamodb" {
  count = local.create && var.dispute_core_table_arn != "" ? 1 : 0

  name = "dispute-core-dynamodb"
  role = aws_iam_role.analysis_execution[0].id

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

resource "aws_iam_role_policy" "dynamodb_stream" {
  count = local.create && local.attach_stream ? 1 : 0

  name = "dispute-core-stream-read"
  role = aws_iam_role.analysis_execution[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetRecords",
          "dynamodb:GetShardIterator",
          "dynamodb:DescribeStream",
          "dynamodb:ListStreams",
        ]
        Resource = var.dispute_core_stream_arn
      },
    ]
  })
}

resource "aws_iam_role_policy" "s3" {
  count = local.s3_policy_enabled ? 1 : 0

  name = "dispute-analysis-s3"
  role = aws_iam_role.analysis_execution[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      length(local.s3_read_only_object_arns) > 0 ? [{
        Sid    = "S3ReadSourceDocuments"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket",
        ]
        Resource = local.s3_read_only_object_arns
      }] : [],
      length(local.s3_object_arns) > 0 ? [{
        Sid    = "S3AnalysisBucketReadWrite"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket",
          "s3:GetBucketLocation",
          "s3:AbortMultipartUpload",
          "s3:ListBucketMultipartUploads",
        ]
        Resource = local.s3_object_arns
      }] : [],
    )
  })
}

resource "aws_iam_role_policy" "ssm" {
  count = local.create && length(var.ssm_parameter_arns) > 0 ? 1 : 0

  name = "dispute-analysis-ssm"
  role = aws_iam_role.analysis_execution[0].id

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

resource "aws_iam_role_policy" "sqs" {
  count = local.create && local.attach_sqs ? 1 : 0

  name = "dispute-agent-fifo-consume"
  role = aws_iam_role.analysis_execution[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility",
        ]
        Resource = var.sqs_queue_arn
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "analysis" {
  count = local.create ? 1 : 0

  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = var.log_retention_in_days

  tags = merge(var.tags, { Purpose = "dispute-agent-analysis-logs" })
}

resource "aws_lambda_function" "analysis" {
  count = local.create ? 1 : 0

  function_name = var.function_name
  description   = "Dual-LLM dispute analysis (bootstrap placeholder; code deployed via CI)."
  role          = aws_iam_role.analysis_execution[0].arn

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
    # GitHub Actions deploy-dispute-analysis-lambda-* updates the deployment package.
    ignore_changes = [
      filename,
      source_code_hash,
    ]
  }

  tags = merge(var.tags, { Purpose = "dispute-agent-analysis-bootstrap" })

  depends_on = [
    aws_cloudwatch_log_group.analysis,
    aws_iam_role_policy_attachment.basic_execution,
  ]
}

resource "aws_lambda_event_source_mapping" "dispute_core_stream" {
  count = local.attach_stream ? 1 : 0

  event_source_arn  = var.dispute_core_stream_arn
  function_name     = aws_lambda_function.analysis[0].function_name
  starting_position = var.stream_starting_position

  batch_size                         = var.stream_batch_size
  maximum_batching_window_in_seconds = var.stream_maximum_batching_window_in_seconds
}

resource "aws_lambda_event_source_mapping" "sqs" {
  count = local.attach_sqs ? 1 : 0

  event_source_arn = var.sqs_queue_arn
  function_name    = aws_lambda_function.analysis[0].arn
  enabled          = true
  batch_size       = var.sqs_batch_size

  scaling_config {
    maximum_concurrency = 2
  }
}
