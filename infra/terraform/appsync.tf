# ============================================================
# AppSync Events API — via CloudFormation (aws provider 5.x 호환)
# ============================================================

resource "aws_cloudformation_stack" "appsync_events" {
  name = "${local.project}-appsync-events"

  template_body = jsonencode({
    AWSTemplateFormatVersion = "2010-09-09"
    Description              = "AppSync Events API for real-time chat streaming"

    Resources = {
      EventApi = {
        Type = "AWS::AppSync::Api"
        Properties = {
          Name = "${local.project}-events"
          EventConfig = {
            AuthProviders = [
              { AuthType = "API_KEY" },
              { AuthType = "AWS_IAM" },
            ]
            ConnectionAuthModes = [
              { AuthType = "API_KEY" },
            ]
            DefaultPublishAuthModes = [
              { AuthType = "AWS_IAM" },
            ]
            DefaultSubscribeAuthModes = [
              { AuthType = "API_KEY" },
            ]
          }
        }
      }

      EventApiKey = {
        Type = "AWS::AppSync::ApiKey"
        Properties = {
          ApiId = { "Fn::GetAtt" = ["EventApi", "ApiId"] }
        }
      }

      DocsNamespace = {
        Type = "AWS::AppSync::ChannelNamespace"
        Properties = {
          ApiId = { "Fn::GetAtt" = ["EventApi", "ApiId"] }
          Name  = "docs"
          PublishAuthModes = [
            { AuthType = "AWS_IAM" },
          ]
          SubscribeAuthModes = [
            { AuthType = "API_KEY" },
          ]
        }
      }
    }

    Outputs = {
      ApiId = {
        Value = { "Fn::GetAtt" = ["EventApi", "ApiId"] }
      }
      HttpDns = {
        Value = { "Fn::GetAtt" = ["EventApi", "Dns.Http"] }
      }
      RealtimeDns = {
        Value = { "Fn::GetAtt" = ["EventApi", "Dns.Realtime"] }
      }
      ApiKey = {
        Value = { "Fn::GetAtt" = ["EventApiKey", "ApiKey"] }
      }
    }
  })

  tags = local.tags
}

# IAM: Allow Lambda to publish events to AppSync
resource "aws_iam_role_policy" "lambda_appsync_publish" {
  name = "${local.project}-lambda-appsync-publish"
  role = aws_iam_role.lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["appsync:EventPublish", "appsync:EventConnect"]
      Resource = ["arn:aws:appsync:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:apis/*/channelNamespace/*"]
    }]
  })
}

# ============================================================
# Outputs
# ============================================================

output "appsync_http_url" {
  value = "https://${aws_cloudformation_stack.appsync_events.outputs["HttpDns"]}"
}

output "appsync_ws_url" {
  value = "wss://${aws_cloudformation_stack.appsync_events.outputs["RealtimeDns"]}"
}

output "appsync_api_key" {
  value     = aws_cloudformation_stack.appsync_events.outputs["ApiKey"]
  sensitive = true
}

output "appsync_api_id" {
  value = aws_cloudformation_stack.appsync_events.outputs["ApiId"]
}
