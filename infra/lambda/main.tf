terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}
provider "aws" { region = var.region }
data "aws_partition" "current" {}
resource "aws_ecr_repository" "images" {
  name                 = var.name
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
}
resource "aws_iam_role" "runtime" {
  name = "${var.name}-runtime"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}
resource "aws_iam_role_policy_attachment" "logs" {
  role       = aws_iam_role.runtime.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}
resource "aws_iam_role_policy" "input" {
  count = var.input_bucket == null ? 0 : 1
  name  = "read-ocr-input-prefix"
  role  = aws_iam_role.runtime.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = "arn:${data.aws_partition.current.partition}:s3:::${var.input_bucket}/${var.input_prefix}*"
    }]
  })
}
resource "aws_cloudwatch_log_group" "ocr" {
  name              = "/aws/lambda/${var.name}"
  retention_in_days = 14
}
resource "aws_lambda_function" "ocr" {
  function_name                  = var.name
  role                           = aws_iam_role.runtime.arn
  package_type                   = "Image"
  image_uri                      = var.image_uri
  architectures                  = ["x86_64"]
  memory_size                    = 2048
  timeout                        = 120
  reserved_concurrent_executions = var.max_concurrency
  environment {
    variables = {
      DOCUMENT_OCR_KYC_LANGS = var.languages
      DOCUMENT_OCR_S3_BUCKET = var.input_bucket == null ? "" : var.input_bucket
      DOCUMENT_OCR_S3_PREFIX = var.input_prefix
    }
  }
  depends_on = [aws_cloudwatch_log_group.ocr, aws_iam_role_policy_attachment.logs, aws_iam_role_policy.input]
}
# No function URL/API Gateway is created; callers use IAM-authorized InvokeFunction.
output "function_name" { value = aws_lambda_function.ocr.function_name }
output "function_arn" { value = aws_lambda_function.ocr.arn }
output "repository_url" { value = aws_ecr_repository.images.repository_url }
