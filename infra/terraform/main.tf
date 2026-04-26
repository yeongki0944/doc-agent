# ============================================================
# AgentCore Doc Agent — Base Infrastructure (Terraform)
# Region: ap-northeast-2, Profile: mzadmin
# ============================================================

locals {
  project = "doc-agent"
  tags = {
    Project     = local.project
    Environment = "demo"
    ManagedBy   = "terraform"
  }
}

# ============================================================
# IAM
# ============================================================

resource "aws_iam_role" "lambda_exec" {
  name = "${local.project}-lambda-exec"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action    = "sts:AssumeRole"
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
      },
      {
        Sid       = "AssumeRolePolicy"
        Action    = "sts:AssumeRole"
        Effect    = "Allow"
        Principal = { Service = "bedrock-agentcore.amazonaws.com" }
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
          ArnLike = {
            "aws:SourceArn" = "arn:aws:bedrock-agentcore:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:*"
          }
        }
      },
      {
        Action    = "sts:AssumeRole"
        Effect    = "Allow"
        Principal = { Service = "bedrock.amazonaws.com" }
      },
    ]
  })
  tags = local.tags
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_dynamodb" {
  name = "${local.project}-lambda-dynamodb"
  role = aws_iam_role.lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "dynamodb:GetItem", "dynamodb:PutItem",
        "dynamodb:UpdateItem", "dynamodb:Query", "dynamodb:Scan"
      ]
      Resource = [
        aws_dynamodb_table.documents.arn,
        aws_dynamodb_table.patch_history.arn,
        aws_dynamodb_table.conversation_history.arn,
      ]
    }]
  })
}

resource "aws_iam_role_policy" "lambda_s3" {
  name = "${local.project}-lambda-s3"
  role = aws_iam_role.lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
      Resource = [
        aws_s3_bucket.artifacts.arn,
        "${aws_s3_bucket.artifacts.arn}/*"
      ]
    }]
  })
}

resource "aws_iam_role_policy" "lambda_bedrock" {
  name = "${local.project}-lambda-bedrock"
  role = aws_iam_role.lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
      Resource = ["*"]
    }]
  })
}

# ============================================================
# S3
# ============================================================

resource "aws_s3_bucket" "artifacts" {
  bucket_prefix = "${local.project}-artifacts-"
  tags          = local.tags
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration { status = "Enabled" }
}

# ============================================================
# DynamoDB
# ============================================================

resource "aws_dynamodb_table" "documents" {
  name         = "${local.project}-documents"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "document_id"
  attribute {
    name = "document_id"
    type = "S"
  }
  tags = local.tags
}

resource "aws_dynamodb_table" "patch_history" {
  name         = "${local.project}-patch-history"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "document_id"
  range_key    = "patch_id"
  attribute {
    name = "document_id"
    type = "S"
  }
  attribute {
    name = "patch_id"
    type = "S"
  }
  tags = local.tags
}

# ============================================================
# Lambda: OnPublish (patch validation)
# ============================================================

data "archive_file" "on_publish_zip" {
  type        = "zip"
  source_file = "${path.module}/../../agent/lambdas/on_publish/handler.py"
  output_path = "${path.module}/on_publish.zip"
}

resource "aws_lambda_function" "on_publish" {
  function_name    = "${local.project}-on-publish"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.on_publish_zip.output_path
  source_code_hash = data.archive_file.on_publish_zip.output_base64sha256
  timeout          = 10
  memory_size      = 128
  tags             = local.tags
}

# ============================================================
# DynamoDB: Conversation History
# ============================================================

resource "aws_dynamodb_table" "conversation_history" {
  name         = "${local.project}-conversation-history"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "document_id"
  range_key    = "session_id"
  attribute {
    name = "document_id"
    type = "S"
  }
  attribute {
    name = "session_id"
    type = "S"
  }
  tags = local.tags
}

# ============================================================
# IAM: Gateway Lambda role (DynamoDB + S3 + Bedrock)
# ============================================================

resource "aws_iam_role" "gateway_lambda_exec" {
  name = "${local.project}-gateway-lambda-exec"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "gateway_lambda_basic" {
  role       = aws_iam_role.gateway_lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "gateway_lambda_dynamodb" {
  name = "${local.project}-gateway-lambda-dynamodb"
  role = aws_iam_role.gateway_lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "dynamodb:GetItem", "dynamodb:PutItem",
        "dynamodb:UpdateItem", "dynamodb:Query", "dynamodb:Scan"
      ]
      Resource = [
        aws_dynamodb_table.documents.arn,
        aws_dynamodb_table.patch_history.arn,
        aws_dynamodb_table.conversation_history.arn,
      ]
    }]
  })
}

resource "aws_iam_role_policy" "gateway_lambda_s3" {
  name = "${local.project}-gateway-lambda-s3"
  role = aws_iam_role.gateway_lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
      Resource = [
        aws_s3_bucket.artifacts.arn,
        "${aws_s3_bucket.artifacts.arn}/*"
      ]
    }]
  })
}

resource "aws_iam_role_policy" "gateway_lambda_bedrock" {
  name = "${local.project}-gateway-lambda-bedrock"
  role = aws_iam_role.gateway_lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
      Resource = ["*"]
    }]
  })
}

# ============================================================
# Lambda: 6 Gateway Target Lambdas
# ============================================================

data "archive_file" "validate_template_zip" {
  type        = "zip"
  source_file = "${path.module}/../../agent/lambdas/gateway_tools/validate_template.py"
  output_path = "${path.module}/validate_template.zip"
}

resource "aws_lambda_function" "validate_template" {
  function_name    = "${local.project}-validate-template"
  role             = aws_iam_role.gateway_lambda_exec.arn
  handler          = "validate_template.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.validate_template_zip.output_path
  source_code_hash = data.archive_file.validate_template_zip.output_base64sha256
  timeout          = 30
  memory_size      = 256
  tags             = local.tags

  environment {
    variables = {
      DOCUMENTS_TABLE = aws_dynamodb_table.documents.name
      S3_BUCKET       = aws_s3_bucket.artifacts.id
    }
  }
}

resource "aws_lambda_permission" "validate_template_agentcore" {
  statement_id  = "AllowAgentCoreGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.validate_template.function_name
  principal     = "bedrock.amazonaws.com"
}

data "archive_file" "generate_diagram_zip" {
  type        = "zip"
  source_file = "${path.module}/../../agent/lambdas/gateway_tools/generate_diagram.py"
  output_path = "${path.module}/generate_diagram.zip"
}

resource "aws_lambda_function" "generate_diagram" {
  function_name    = "${local.project}-generate-diagram"
  role             = aws_iam_role.gateway_lambda_exec.arn
  handler          = "generate_diagram.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.generate_diagram_zip.output_path
  source_code_hash = data.archive_file.generate_diagram_zip.output_base64sha256
  timeout          = 60
  memory_size      = 512
  tags             = local.tags

  environment {
    variables = {
      S3_BUCKET = aws_s3_bucket.artifacts.id
    }
  }
}

resource "aws_lambda_permission" "generate_diagram_agentcore" {
  statement_id  = "AllowAgentCoreGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.generate_diagram.function_name
  principal     = "bedrock.amazonaws.com"
}

data "archive_file" "estimate_cost_zip" {
  type        = "zip"
  source_file = "${path.module}/../../agent/lambdas/gateway_tools/estimate_cost.py"
  output_path = "${path.module}/estimate_cost.zip"
}

resource "aws_lambda_function" "estimate_cost" {
  function_name    = "${local.project}-estimate-cost"
  role             = aws_iam_role.gateway_lambda_exec.arn
  handler          = "estimate_cost.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.estimate_cost_zip.output_path
  source_code_hash = data.archive_file.estimate_cost_zip.output_base64sha256
  timeout          = 60
  memory_size      = 256
  tags             = local.tags

  environment {
    variables = {
      S3_BUCKET = aws_s3_bucket.artifacts.id
    }
  }
}

resource "aws_lambda_permission" "estimate_cost_agentcore" {
  statement_id  = "AllowAgentCoreGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.estimate_cost.function_name
  principal     = "bedrock.amazonaws.com"
}

data "archive_file" "calc_staffing_zip" {
  type        = "zip"
  source_file = "${path.module}/../../agent/lambdas/gateway_tools/calc_staffing.py"
  output_path = "${path.module}/calc_staffing.zip"
}

resource "aws_lambda_function" "calc_staffing" {
  function_name    = "${local.project}-calc-staffing"
  role             = aws_iam_role.gateway_lambda_exec.arn
  handler          = "calc_staffing.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.calc_staffing_zip.output_path
  source_code_hash = data.archive_file.calc_staffing_zip.output_base64sha256
  timeout          = 30
  memory_size      = 256
  tags             = local.tags

  environment {
    variables = {
      DOCUMENTS_TABLE = aws_dynamodb_table.documents.name
    }
  }
}

resource "aws_lambda_permission" "calc_staffing_agentcore" {
  statement_id  = "AllowAgentCoreGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.calc_staffing.function_name
  principal     = "bedrock.amazonaws.com"
}

data "archive_file" "export_docx_zip" {
  type        = "zip"
  source_file = "${path.module}/../../agent/lambdas/gateway_tools/export_docx.py"
  output_path = "${path.module}/export_docx.zip"
}

resource "aws_lambda_function" "export_docx" {
  function_name    = "${local.project}-export-docx"
  role             = aws_iam_role.gateway_lambda_exec.arn
  handler          = "export_docx.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.export_docx_zip.output_path
  source_code_hash = data.archive_file.export_docx_zip.output_base64sha256
  timeout          = 60
  memory_size      = 512
  tags             = local.tags

  environment {
    variables = {
      S3_BUCKET = aws_s3_bucket.artifacts.id
    }
  }
}

resource "aws_lambda_permission" "export_docx_agentcore" {
  statement_id  = "AllowAgentCoreGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.export_docx.function_name
  principal     = "bedrock.amazonaws.com"
}

data "archive_file" "build_milestones_zip" {
  type        = "zip"
  source_file = "${path.module}/../../agent/lambdas/gateway_tools/build_milestones.py"
  output_path = "${path.module}/build_milestones.zip"
}

resource "aws_lambda_function" "build_milestones" {
  function_name    = "${local.project}-build-milestones"
  role             = aws_iam_role.gateway_lambda_exec.arn
  handler          = "build_milestones.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.build_milestones_zip.output_path
  source_code_hash = data.archive_file.build_milestones_zip.output_base64sha256
  timeout          = 30
  memory_size      = 256
  tags             = local.tags

  environment {
    variables = {
      DOCUMENTS_TABLE = aws_dynamodb_table.documents.name
    }
  }
}

resource "aws_lambda_permission" "build_milestones_agentcore" {
  statement_id  = "AllowAgentCoreGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.build_milestones.function_name
  principal     = "bedrock.amazonaws.com"
}

# ============================================================
# Lambda: Document API (Bedrock-powered)
# ============================================================

data "archive_file" "document_api_zip" {
  type        = "zip"
  source_file = "${path.module}/../../agent/lambdas/document_api/handler.py"
  output_path = "${path.module}/document_api.zip"
}

resource "aws_lambda_function" "document_api" {
  function_name    = "${local.project}-document-api"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.document_api_zip.output_path
  source_code_hash = data.archive_file.document_api_zip.output_base64sha256
  timeout          = 60
  memory_size      = 256
  tags             = local.tags

  environment {
    variables = {
      DOCUMENTS_TABLE            = aws_dynamodb_table.documents.name
      CONVERSATION_HISTORY_TABLE = aws_dynamodb_table.conversation_history.name
    }
  }
}

# Lambda Function URL (may be blocked by SCP — API Gateway is primary)
resource "aws_lambda_function_url" "document_api_url" {
  function_name      = aws_lambda_function.document_api.function_name
  authorization_type = "NONE"

  cors {
    allow_origins = ["*"]
    allow_methods = ["*"]
    allow_headers = ["content-type"]
    max_age       = 3600
  }
}

# ============================================================
# API Gateway HTTP (primary API endpoint)
# ============================================================

resource "aws_apigatewayv2_api" "document_api" {
  name          = "${local.project}-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["Content-Type"]
    max_age       = 3600
  }

  tags = local.tags
}

resource "aws_apigatewayv2_integration" "document_api" {
  api_id                 = aws_apigatewayv2_api.document_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.document_api.invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 30000
}

resource "aws_apigatewayv2_route" "catch_all" {
  api_id    = aws_apigatewayv2_api.document_api.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.document_api.id}"
}

# POST /invocations → proxied to document_api Lambda, which routes to AgentCore Runtime
resource "aws_apigatewayv2_route" "invocations" {
  api_id    = aws_apigatewayv2_api.document_api.id
  route_key = "POST /invocations"
  target    = "integrations/${aws_apigatewayv2_integration.document_api.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.document_api.id
  name        = "$default"
  auto_deploy = true
  tags        = local.tags
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.document_api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.document_api.execution_arn}/*/*"
}

# ============================================================
# Frontend: S3 + CloudFront
# ============================================================

resource "aws_s3_bucket" "frontend" {
  bucket_prefix = "${local.project}-frontend-"
  tags          = local.tags
}

resource "aws_s3_bucket_website_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  index_document { suffix = "index.html" }
  error_document { key = "index.html" }
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${local.project}-frontend-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  default_root_object = "index.html"
  tags                = local.tags

  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = "s3-frontend"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  default_cache_behavior {
    target_origin_id       = "s3-frontend"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    forwarded_values {
      query_string = false
      cookies { forward = "none" }
    }
    min_ttl     = 0
    default_ttl = 300
    max_ttl     = 86400
  }

  custom_error_response {
    error_code         = 403
    response_code      = 200
    response_page_path = "/index.html"
  }
  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowCloudFrontOAC"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.frontend.arn}/*"
      Condition = {
        StringEquals = {
          "AWS:SourceArn" = aws_cloudfront_distribution.frontend.arn
        }
      }
    }]
  })
}

# ============================================================
# Outputs
# ============================================================

output "s3_bucket" {
  value = aws_s3_bucket.artifacts.id
}

output "documents_table" {
  value = aws_dynamodb_table.documents.name
}

output "patch_history_table" {
  value = aws_dynamodb_table.patch_history.name
}

output "lambda_on_publish_arn" {
  value = aws_lambda_function.on_publish.arn
}

output "lambda_exec_role_arn" {
  value = aws_iam_role.lambda_exec.arn
}

output "api_url" {
  value = aws_lambda_function_url.document_api_url.function_url
}

output "api_gateway_url" {
  value = aws_apigatewayv2_stage.default.invoke_url
}

output "frontend_bucket" {
  value = aws_s3_bucket.frontend.id
}

output "cloudfront_domain" {
  value = aws_cloudfront_distribution.frontend.domain_name
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.frontend.id
}

output "conversation_history_table" {
  value = aws_dynamodb_table.conversation_history.name
}

output "lambda_validate_template_arn" {
  value = aws_lambda_function.validate_template.arn
}

output "lambda_generate_diagram_arn" {
  value = aws_lambda_function.generate_diagram.arn
}

output "lambda_estimate_cost_arn" {
  value = aws_lambda_function.estimate_cost.arn
}

output "lambda_calc_staffing_arn" {
  value = aws_lambda_function.calc_staffing.arn
}

output "lambda_export_docx_arn" {
  value = aws_lambda_function.export_docx.arn
}

output "lambda_build_milestones_arn" {
  value = aws_lambda_function.build_milestones.arn
}
