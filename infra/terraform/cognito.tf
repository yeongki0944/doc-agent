# ============================================================
# Cognito User Pool — Email + Password (Hosted UI)
# ============================================================

resource "aws_cognito_user_pool" "main" {
  name = "${local.project}-users"

  # 이메일을 username으로 사용
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length                   = 8
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = false
    require_uppercase                = false
    temporary_password_validity_days = 7
  }

  # 가입 시 이메일 인증 코드 발송
  verification_message_template {
    default_email_option = "CONFIRM_WITH_CODE"
    email_subject        = "Doc Agent — 이메일 인증 코드"
    email_message        = "인증 코드: {####}"
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true
  }

  tags = local.tags

  # Pre Sign-up Lambda trigger (email domain restriction)
  lambda_config {
    pre_sign_up = aws_lambda_function.pre_signup.arn
  }
}

# ============================================================
# App Client — SPA (no client secret, PKCE)
# ============================================================

resource "aws_cognito_user_pool_client" "frontend" {
  name         = "${local.project}-frontend"
  user_pool_id = aws_cognito_user_pool.main.id

  generate_secret = false  # SPA는 secret 못 가짐

  # OAuth 설정 (Hosted UI 사용)
  allowed_oauth_flows                  = ["code"]   # Authorization Code + PKCE
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]

  # 로그인 후 돌아올 URL (CloudFront + 로컬 dev)
  callback_urls = [
    "https://${aws_cloudfront_distribution.frontend.domain_name}/",
    "https://${aws_cloudfront_distribution.frontend.domain_name}/callback",
    "http://localhost:5173/",
    "http://localhost:5173/callback",
  ]

  logout_urls = [
    "https://${aws_cloudfront_distribution.frontend.domain_name}/",
    "http://localhost:5173/",
  ]

  # 직접 로그인(SDK)도 허용 — 나중에 커스텀 UI 만들 때 대비
  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  # 토큰 만료
  access_token_validity  = 1   # hour
  id_token_validity      = 1   # hour
  refresh_token_validity = 30  # days

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }

  prevent_user_existence_errors = "ENABLED"
}

# ============================================================
# Hosted UI Domain — globally unique within region
# ============================================================

resource "aws_cognito_user_pool_domain" "main" {
  domain       = "${local.project}-${data.aws_caller_identity.current.account_id}"
  user_pool_id = aws_cognito_user_pool.main.id
}

# ============================================================
# Outputs
# ============================================================

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.main.id
}

output "cognito_user_pool_client_id" {
  value = aws_cognito_user_pool_client.frontend.id
}

output "cognito_hosted_ui_domain" {
  # 예: https://doc-agent-626635430480.auth.ap-northeast-2.amazoncognito.com
  value = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${data.aws_region.current.name}.amazoncognito.com"
}

output "cognito_issuer" {
  value = "https://cognito-idp.${data.aws_region.current.name}.amazonaws.com/${aws_cognito_user_pool.main.id}"
}

# ============================================================
# Pre Sign-up Lambda (email domain restriction)
# ============================================================

data "archive_file" "pre_signup_zip" {
  type        = "zip"
  source_file = "${path.module}/../../agent/lambdas/pre_signup/handler.py"
  output_path = "${path.module}/pre_signup.zip"
}

resource "aws_lambda_function" "pre_signup" {
  function_name    = "${local.project}-pre-signup"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.pre_signup_zip.output_path
  source_code_hash = data.archive_file.pre_signup_zip.output_base64sha256
  timeout          = 5
  memory_size      = 128
  tags             = local.tags
}

resource "aws_lambda_permission" "cognito_pre_signup" {
  statement_id  = "AllowCognitoInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.pre_signup.function_name
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = aws_cognito_user_pool.main.arn
}