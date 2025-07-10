terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}


data "aws_eks_cluster_auth" "cluster" {
  name = module.eks.cluster_name
}


resource "null_resource" "update_kubeconfig" {
  depends_on = [module.eks]
  
  provisioner "local-exec" {
    command = "aws eks --region ${var.aws_region} update-kubeconfig --name ${module.eks.cluster_name}"
  }
}