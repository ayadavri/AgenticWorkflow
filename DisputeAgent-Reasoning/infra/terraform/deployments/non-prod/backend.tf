terraform {
  backend "s3" {
    bucket  = "ri-terraform-state-bucket-test"
    key     = "dispute-agent/non-prod/terraform.tfstate"
    region  = "us-east-1"
    encrypt = true
    profile = "dev-session"
  }
}
