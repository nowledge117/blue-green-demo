variable "aws_region" {
  description = "The AWS region to deploy resources in."
  type        = string
  default     = "ap-south-1"
}

variable "cluster_name" {
  description = "The name for the EKS cluster."
  type        = string
  default     = "blue-green-demo-cluster"
}

variable "k8s_version" {
  description = "The Kubernetes version for the EKS cluster."
  type        = string
  default     = "1.28"
}