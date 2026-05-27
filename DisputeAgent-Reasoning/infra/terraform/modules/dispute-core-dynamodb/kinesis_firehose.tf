# CDC path: DynamoDB → Kinesis Data Stream (streaming destination) → Firehose → S3 (existing datalake bucket).

data "aws_s3_bucket" "firehose_destination" {
  count  = local.cdc_to_datalake_enabled ? 1 : 0
  bucket = var.firehose_destination_s3_bucket_name
}

resource "aws_kinesis_stream" "dispute_core_cdc" {
  count = local.cdc_to_datalake_enabled ? 1 : 0

  name        = var.dispute_core_cdc_kinesis_stream_name
  shard_count = var.dispute_core_cdc_kinesis_shard_count

  retention_period = var.dispute_core_cdc_kinesis_retention_hours

  tags = merge(var.tags, { Purpose = "dispute-core-ddb-cdc" })
}

resource "aws_dynamodb_kinesis_streaming_destination" "dispute_core" {
  count = local.cdc_to_datalake_enabled ? 1 : 0

  table_name = aws_dynamodb_table.dispute_core.name
  stream_arn = aws_kinesis_stream.dispute_core_cdc[0].arn

  depends_on = [
    aws_dynamodb_table.dispute_core,
    aws_kinesis_stream.dispute_core_cdc,
  ]
}

data "aws_iam_policy_document" "firehose_dispute_core_assume" {
  count = local.cdc_to_datalake_enabled ? 1 : 0

  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["firehose.amazonaws.com"]
    }
  }
}

resource "aws_cloudwatch_log_group" "firehose_dispute_core" {
  count = local.cdc_to_datalake_enabled ? 1 : 0

  name              = "/aws/kinesis-firehose/${replace(var.dispute_core_cdc_kinesis_stream_name, "/", "-")}"
  retention_in_days = var.firehose_log_retention_days
  tags              = var.tags
}

resource "aws_cloudwatch_log_stream" "firehose_s3_delivery" {
  count = local.cdc_to_datalake_enabled ? 1 : 0

  name           = "DestinationDelivery"
  log_group_name = aws_cloudwatch_log_group.firehose_dispute_core[0].name
}

resource "aws_iam_role" "firehose_dispute_core" {
  count = local.cdc_to_datalake_enabled ? 1 : 0

  name               = substr("${replace(var.dispute_core_cdc_kinesis_stream_name, "_", "-")}-fh", 0, 64)
  assume_role_policy = data.aws_iam_policy_document.firehose_dispute_core_assume[0].json
  tags               = merge(var.tags, { Purpose = "dispute-core-ddb-cdc-firehose" })
}

resource "aws_iam_role_policy" "firehose_dispute_core" {
  count = local.cdc_to_datalake_enabled ? 1 : 0

  name = "kinesis-to-s3"
  role = aws_iam_role.firehose_dispute_core[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3Destination"
        Effect = "Allow"
        Action = [
          "s3:AbortMultipartUpload",
          "s3:GetBucketLocation",
          "s3:GetObject",
          "s3:ListBucket",
          "s3:ListBucketMultipartUploads",
          "s3:PutObject",
        ]
        Resource = [
          data.aws_s3_bucket.firehose_destination[0].arn,
          "${data.aws_s3_bucket.firehose_destination[0].arn}/*",
        ]
      },
      {
        Sid    = "KinesisSource"
        Effect = "Allow"
        Action = [
          "kinesis:DescribeStream",
          "kinesis:GetShardIterator",
          "kinesis:GetRecords",
          "kinesis:ListShards",
        ]
        Resource = aws_kinesis_stream.dispute_core_cdc[0].arn
      },
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:DescribeLogStreams",
          "logs:PutLogEvents",
        ]
        Resource = [
          aws_cloudwatch_log_group.firehose_dispute_core[0].arn,
          "${aws_cloudwatch_log_group.firehose_dispute_core[0].arn}:log-stream:*",
        ]
      },
    ]
  })
}

resource "aws_kinesis_firehose_delivery_stream" "dispute_core_cdc" {
  count = local.cdc_to_datalake_enabled ? 1 : 0

  name        = substr("${replace(var.dispute_core_cdc_kinesis_stream_name, "_", "-")}-fh", 0, 64)
  destination = "extended_s3"

  kinesis_source_configuration {
    kinesis_stream_arn = aws_kinesis_stream.dispute_core_cdc[0].arn
    role_arn           = aws_iam_role.firehose_dispute_core[0].arn
  }

  extended_s3_configuration {
    role_arn   = aws_iam_role.firehose_dispute_core[0].arn
    bucket_arn = data.aws_s3_bucket.firehose_destination[0].arn

    prefix              = var.firehose_s3_prefix
    error_output_prefix = var.firehose_s3_error_output_prefix

    buffering_interval = var.firehose_buffer_interval_seconds
    buffering_size     = var.firehose_buffer_size_mb

    compression_format = var.firehose_compression_format
    file_extension     = var.firehose_s3_file_extension

    cloudwatch_logging_options {
      enabled         = true
      log_group_name  = aws_cloudwatch_log_group.firehose_dispute_core[0].name
      log_stream_name = aws_cloudwatch_log_stream.firehose_s3_delivery[0].name
    }
  }

  tags = merge(var.tags, { Purpose = "dispute-core-ddb-cdc-firehose" })

  depends_on = [
    aws_iam_role_policy.firehose_dispute_core,
    aws_cloudwatch_log_stream.firehose_s3_delivery,
  ]
}
