resource "aws_ecr_repository" "app_repo" {
  name                 = "blue-green-app"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}