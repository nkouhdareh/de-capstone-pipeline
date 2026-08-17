# Shared account infrastructure, created before this project and used by other
# repositories. Read only - Terraform must never own or replace it.
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

# The role assumed by .github/workflows/s3-contract.yml.
# Imported, never created: see imports.tf.
resource "aws_iam_role" "github_actions" {
  name        = "de-capstone-github-actions"
  description = "GitHub Actions OIDC for nkouhdareh/de-capstone-pipeline. Read-only on the silver/drug_event S3 prefix. No write, no delete."

  # Ceiling on the role's effective permissions, whatever its policy says.
  # de-capstone-terraform is denied PutRolePermissionsBoundary everywhere, so
  # Terraform cannot lift the cap it operates under.
  permissions_boundary = "arn:aws:iam::617371012792:policy/de-capstone-github-actions-boundary"

  # Reproduced exactly as it exists today, wildcard included. Tightening this
  # to the two exact subjects is a separate, reviewed pull request.
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "GitHubOIDCDeCapstoneRepoOnly"
        Effect = "Allow"
        Principal = {
          Federated = data.aws_iam_openid_connect_provider.github.arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" = "repo:nkouhdareh@263947291/de-capstone-pipeline@1320110552:*"
          }
        }
      }
    ]
  })

  # Phases 4 and 5 depend on this role. Terraform must never plan its removal.
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role_policy" "s3_read" {
  name = "de-capstone-github-actions-s3-read"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ListOnlyTheFallbackPrefix"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = "arn:aws:s3:::de-capstone-pv-617371012792"
        Condition = {
          StringLike = {
            "s3:prefix" = [
              "silver/drug_event/",
              "silver/drug_event/*"
            ]
          }
        }
      },
      {
        Sid      = "GetOnlyFallbackObjects"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "arn:aws:s3:::de-capstone-pv-617371012792/silver/drug_event/*"
      }
    ]
  })

  lifecycle {
    prevent_destroy = true
  }
}