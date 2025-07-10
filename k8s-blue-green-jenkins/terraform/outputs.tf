output "cluster_name" {
  description = "The name of the EKS cluster."
  value       = module.eks.cluster_name
}

output "jenkins_iam_role_arn" {
  description = "The ARN of the IAM role for the Jenkins service account."
  value       = aws_iam_role.jenkins_role.arn
}

output "aws_region" {
  description = "The AWS region where resources are deployed."
  value       = var.aws_region
}