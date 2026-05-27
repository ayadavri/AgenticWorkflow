#!/usr/bin/env bash
# Pull terraform.tfvars from S3 and run terraform plan (state: s3://ri-terraform-state-bucket-test/dispute-agent/non-prod/terraform.tfstate)

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

S3_BUCKET="ri-terraform-state-bucket-test"
S3_KEY="dispute-agent/non-prod/terraform.tfvars"
TFVARS_FILE="terraform.tfvars"
AWS_PROFILE="dev-session"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Terraform Plan - dispute-agent non-prod${NC}"
echo -e "${BLUE}========================================${NC}"
echo

command -v aws >/dev/null || { echo -e "${RED}Error: AWS CLI is not installed${NC}"; exit 1; }
command -v terraform >/dev/null || { echo -e "${RED}Error: Terraform is not installed${NC}"; exit 1; }

echo -e "${YELLOW}Checking AWS credentials (profile: ${AWS_PROFILE})...${NC}"
if ! aws sts get-caller-identity --profile "$AWS_PROFILE" >/dev/null 2>&1; then
  echo -e "${RED}Error: AWS credentials not configured or expired${NC}"
  echo -e "${YELLOW}Run: aws sso login --profile ${AWS_PROFILE}${NC}"
  exit 1
fi

echo -e "${YELLOW}Downloading terraform.tfvars from S3...${NC}"
echo "  s3://${S3_BUCKET}/${S3_KEY}"
if aws s3 cp "s3://${S3_BUCKET}/${S3_KEY}" "$TFVARS_FILE" --profile "$AWS_PROFILE" >/dev/null 2>&1; then
  echo -e "${GREEN}Downloaded terraform.tfvars${NC}"
else
  echo -e "${YELLOW}Could not download tfvars from S3; using local file if present${NC}"
  [[ -f "$TFVARS_FILE" ]] || { echo -e "${RED}No local terraform.tfvars found${NC}"; exit 1; }
fi

echo
if [[ ! -d .terraform ]]; then
  echo -e "${YELLOW}Initializing Terraform (S3 backend)...${NC}"
  terraform init
else
  echo -e "${GREEN}Terraform already initialized${NC}"
fi

echo
echo -e "${YELLOW}Validating Terraform configuration...${NC}"
terraform validate

echo
echo -e "${BLUE}Running Terraform plan...${NC}"
terraform plan -var-file="$TFVARS_FILE"
