terraform {
  backend "s3" {
    bucket  = "ri-terraform-state-bucket-prod"
    key     = "dispute-agent/prod/terraform.tfstate"
    region  = "us-east-1"
    encrypt = true
    # Use a profile that can access this bucket in the production account (update if needed).
    profile = "prod-session"
  }
}
