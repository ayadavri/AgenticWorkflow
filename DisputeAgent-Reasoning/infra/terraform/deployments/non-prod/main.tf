provider "aws" {
  region = var.aws_region
  # Prevent accidental apply to the wrong account
  allowed_account_ids = [var.aws_account_id]
  profile             = var.aws_profile != "" ? var.aws_profile : null
}

module "dispute_core_dynamodb" {
  source = "../../modules/dispute-core-dynamodb"

  table_name   = var.dynamodb_table_name
  billing_mode = var.dynamodb_billing_mode

  stream_enabled   = var.dynamodb_stream_enabled
  stream_view_type = var.dynamodb_stream_view_type

  stream_lambda_function_name     = var.dispute_core_stream_lambda_function_name
  create_stream_lambda            = var.dynamodb_create_stream_lambda
  attach_stream_lambda            = var.dynamodb_attach_stream_lambda
  stream_lambda_environment_extra = var.dispute_core_stream_lambda_environment_extra

  attributes               = var.dynamodb_attributes
  global_secondary_indexes = var.dynamodb_global_secondary_indexes

  firehose_destination_s3_bucket_name  = var.dispute_core_firehose_s3_bucket
  dispute_core_cdc_kinesis_stream_name = var.dispute_core_cdc_kinesis_stream_name
  dispute_core_cdc_kinesis_shard_count = var.dispute_core_cdc_kinesis_shard_count
  firehose_s3_prefix                   = var.dispute_core_firehose_s3_prefix
  firehose_s3_error_output_prefix      = var.dispute_core_firehose_s3_error_output_prefix

  tags = merge(
    {
      Service = "collections-core"
      Domain  = "disputes"
    },
    var.tags,
  )
}

module "dispute_agent_fifo" {
  source = "../../modules/dispute-sqs-fifo"

  queue_name                  = var.dispute_agent_fifo_queue_name
  visibility_timeout_seconds  = var.dispute_agent_fifo_visibility_timeout_seconds
  redrive_max_receive_count   = var.dispute_agent_fifo_redrive_max_receive_count
  content_based_deduplication = true

  tags = merge(
    {
      Service = "collections-core"
      Domain  = "disputes"
    },
    var.tags,
  )
}

module "dispute_event_bus" {
  source = "../../modules/dispute-event-bus"

  opensearch_rule_sqs_target_arn     = local.dispute_event_bus_opensearch_target_sqs_arn
  temporal_rule_sqs_target_arn       = local.dispute_event_bus_temporal_target_sqs_arn
  agentic_ai_rule_sqs_target_enabled = true
  agentic_ai_rule_sqs_target_arn     = module.dispute_agent_fifo.queue_arn
  event_archive_retention_days       = 7

  tags = merge(
    {
      Service = "collections-core"
      Domain  = "disputes"
    },
    var.tags,
  )
}

# Allow EventBridge rule disputes-core-invokeAgenticAI to deliver to the FIFO queue.
module "dispute_analysis_lambda" {
  source = "../../modules/dispute-analysis-lambda"

  function_name = var.dispute_analysis_lambda_function_name
  create_lambda = var.dispute_analysis_lambda_create

  dispute_core_table_arn  = module.dispute_core_dynamodb.table_arn
  dispute_core_stream_arn = module.dispute_core_dynamodb.stream_arn

  attach_stream_event_source = var.dispute_analysis_lambda_attach_stream
  attach_sqs_event_source    = var.dispute_analysis_lambda_attach_sqs
  sqs_queue_arn              = module.dispute_agent_fifo.queue_arn

  s3_bucket_arns = [
    for name in var.dispute_analysis_lambda_s3_bucket_names :
    "arn:aws:s3:::${name}"
  ]

  s3_read_only_bucket_arns = [
    for name in var.dispute_analysis_lambda_s3_read_bucket_names :
    "arn:aws:s3:::${name}"
  ]

  ssm_parameter_arns = [
    for name in var.dispute_analysis_lambda_ssm_parameter_names :
    "arn:aws:ssm:${var.aws_region}:${var.aws_account_id}:parameter/${name}"
  ]

  # Do not set AWS_REGION — Lambda reserves it and injects the runtime region automatically.
  environment_variables = merge(
    {
      AWS_DYNAMODB_TABLE = var.dynamodb_table_name
      RI_CORE_BASE_URL   = var.ri_core_base_url
    },
    var.dispute_analysis_lambda_environment_extra,
  )

  tags = merge(
    {
      Service = "dispute-agent"
      Domain  = "disputes"
    },
    var.tags,
  )
}

module "dispute_judgment_lambda" {
  source = "../../modules/dispute-judgment-lambda"

  function_name = var.dispute_judgment_lambda_function_name
  create_lambda = var.dispute_judgment_lambda_create

  dispute_core_table_arn = module.dispute_core_dynamodb.table_arn

  enable_daily_schedule = var.dispute_judgment_lambda_enable_daily_schedule
  schedule_expression   = var.dispute_judgment_lambda_schedule_expression

  s3_bucket_arns = [
    for name in var.dispute_judgment_lambda_s3_bucket_names :
    "arn:aws:s3:::${name}"
  ]

  ssm_parameter_arns = [
    for name in var.dispute_judgment_lambda_ssm_parameter_names :
    "arn:aws:ssm:${var.aws_region}:${var.aws_account_id}:parameter/${name}"
  ]

  environment_variables = merge(
    {
      AWS_DYNAMODB_TABLE = var.dynamodb_table_name
      RI_CORE_BASE_URL   = var.ri_core_base_url
    },
    var.dispute_judgment_lambda_environment_extra,
  )

  tags = merge(
    {
      Service = "dispute-agent"
      Domain  = "disputes"
    },
    var.tags,
  )
}

resource "aws_sqs_queue_policy" "dispute_agent_fifo_eventbridge" {
  queue_url = module.dispute_agent_fifo.queue_id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowEventBridgeAgenticRule"
        Effect = "Allow"
        Principal = {
          Service = "events.amazonaws.com"
        }
        Action   = "sqs:SendMessage"
        Resource = module.dispute_agent_fifo.queue_arn
        Condition = {
          ArnEquals = {
            "aws:SourceArn" = module.dispute_event_bus.rule_arns["agentic_ai"]
          }
          StringEquals = {
            "aws:SourceAccount" = var.aws_account_id
          }
        }
      },
    ]
  })
}
