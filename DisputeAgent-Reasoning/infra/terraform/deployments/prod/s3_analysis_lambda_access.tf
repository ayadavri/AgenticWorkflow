# Staging bucket + policy so dispute-agent-analysis-exec can stage Consumer/Creditor PDFs.
# Set create_case_dispute_analysis_s3_bucket = false if the bucket already exists outside Terraform.

data "aws_s3_bucket" "case_dispute_analysis" {
  count  = var.create_case_dispute_analysis_s3_bucket ? 0 : 1
  bucket = var.dispute_analysis_lambda_s3_bucket_names[0]
}

resource "aws_s3_bucket" "case_dispute_analysis" {
  count  = var.create_case_dispute_analysis_s3_bucket ? 1 : 0
  bucket = var.dispute_analysis_lambda_s3_bucket_names[0]

  tags = merge(
    var.tags,
    {
      Purpose = "dispute-analysis-staging"
    },
  )
}

resource "aws_s3_bucket_public_access_block" "case_dispute_analysis" {
  count = var.create_case_dispute_analysis_s3_bucket ? 1 : 0

  bucket = aws_s3_bucket.case_dispute_analysis[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "case_dispute_analysis" {
  count = var.create_case_dispute_analysis_s3_bucket ? 1 : 0

  bucket = aws_s3_bucket.case_dispute_analysis[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

locals {
  dispute_analysis_lambda_role_arn = "arn:aws:iam::${var.aws_account_id}:role/${var.dispute_analysis_lambda_function_name}-exec"
  case_dispute_analysis_bucket_id  = var.create_case_dispute_analysis_s3_bucket ? aws_s3_bucket.case_dispute_analysis[0].id : data.aws_s3_bucket.case_dispute_analysis[0].id
  case_dispute_analysis_bucket_arn = var.create_case_dispute_analysis_s3_bucket ? aws_s3_bucket.case_dispute_analysis[0].arn : data.aws_s3_bucket.case_dispute_analysis[0].arn
}

resource "aws_s3_bucket_policy" "case_dispute_analysis_dispute_agent" {
  bucket = local.case_dispute_analysis_bucket_id

  # Analysis Lambda IAM role must exist before attaching a Principal-scoped bucket policy.
  depends_on = [module.dispute_analysis_lambda]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowDisputeAgentAnalysisReadWrite"
        Effect = "Allow"
        Principal = {
          AWS = local.dispute_analysis_lambda_role_arn
        }
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket",
          "s3:GetBucketLocation",
          "s3:AbortMultipartUpload",
          "s3:ListBucketMultipartUploads",
        ]
        Resource = [
          local.case_dispute_analysis_bucket_arn,
          "${local.case_dispute_analysis_bucket_arn}/*",
        ]
      },
    ]
  })
}
