# Declarative imports: they appear in the plan on the pull request, so the
# takeover is reviewed before it happens. Both resources already exist -
# de-capstone-terraform is explicitly denied iam:CreateRole, so Terraform
# could not create them even if the config said so.

import {
  to = aws_iam_role.github_actions
  id = "de-capstone-github-actions"
}

import {
  to = aws_iam_role_policy.s3_read
  id = "de-capstone-github-actions:de-capstone-github-actions-s3-read"
}