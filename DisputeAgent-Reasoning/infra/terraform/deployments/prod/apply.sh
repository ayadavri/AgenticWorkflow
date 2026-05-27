#!/usr/bin/env bash
# Plan with local terraform.tfvars, prompt for approval, upload tfvars to S3, apply saved plan
# State backend: prod/backend.tf (s3://ri-terraform-state-bucket-prod/dispute-agent/prod/terraform.tfstate)
# tfvars mirror (optional CI): uploads to prod account bucket below

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

S3_BUCKET="ri-terraform-state-bucket-prod"
S3_KEY="dispute-agent/prod/terraform.tfvars"
TFVARS_FILE="terraform.tfvars"
AWS_PROFILE="prod-session"
PLAN_OUTPUT_FILE=".terraform-plan-output.txt"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Terraform Apply - dispute-agent prod${NC}"
echo -e "${BLUE}========================================${NC}"
echo

command -v aws >/dev/null || { echo -e "${RED}Error: AWS CLI is not installed${NC}"; exit 1; }
command -v terraform >/dev/null || { echo -e "${RED}Error: Terraform is not installed${NC}"; exit 1; }
[[ -f "$TFVARS_FILE" ]] || { echo -e "${RED}Error: ${TFVARS_FILE} not found${NC}"; exit 1; }

echo -e "${YELLOW}Checking AWS credentials (profile: ${AWS_PROFILE})...${NC}"
if ! aws sts get-caller-identity --profile "$AWS_PROFILE" >/dev/null 2>&1; then
  echo -e "${RED}Error: AWS credentials not configured or expired${NC}"
  echo -e "${YELLOW}Run: aws sso login --profile ${AWS_PROFILE}${NC}"
  exit 1
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
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Running Terraform Plan${NC}"
echo -e "${BLUE}========================================${NC}"
echo

if terraform plan -var-file="$TFVARS_FILE" -out=tfplan.binary 2>&1 | tee "$PLAN_OUTPUT_FILE"; then
  PLAN_EXIT_CODE=0
else
  PLAN_EXIT_CODE=$?
fi

if [[ $PLAN_EXIT_CODE -ne 0 ]]; then
  echo -e "${RED}Terraform plan failed (exit code: ${PLAN_EXIT_CODE})${NC}"
  rm -f "$PLAN_OUTPUT_FILE" tfplan.binary
  exit "$PLAN_EXIT_CODE"
fi

if grep -q "No changes" "$PLAN_OUTPUT_FILE" 2>/dev/null; then
  echo -e "${GREEN}No changes detected. Infrastructure is up to date.${NC}"
  rm -f "$PLAN_OUTPUT_FILE" tfplan.binary
  exit 0
fi

echo
echo -e "${CYAN}----------------------------------------${NC}"
echo -e "${YELLOW}Changes detected in Terraform plan${NC}"
echo -e "${CYAN}----------------------------------------${NC}"
echo
echo -e "${YELLOW}Do you want to proceed with applying these changes?${NC}"
echo -e "${YELLOW}This will:${NC}"
echo -e "  1. Upload local ${TFVARS_FILE} to s3://${S3_BUCKET}/${S3_KEY}"
echo -e "  2. Apply Terraform changes to the S3 remote state"
echo
read -r -p "Type 'yes' to continue, or anything else to cancel: " REPLY
echo

if [[ ! "$REPLY" =~ ^[Yy][Ee][Ss]$ ]]; then
  echo -e "${YELLOW}Apply cancelled by user${NC}"
  rm -f "$PLAN_OUTPUT_FILE" tfplan.binary
  exit 0
fi

echo -e "${YELLOW}Uploading ${TFVARS_FILE} to S3...${NC}"
if aws s3 cp "$TFVARS_FILE" "s3://${S3_BUCKET}/${S3_KEY}" --profile "$AWS_PROFILE" >/dev/null 2>&1; then
  echo -e "${GREEN}Uploaded ${TFVARS_FILE} to S3${NC}"
else
  echo -e "${RED}Failed to upload ${TFVARS_FILE} to S3${NC}"
  echo -e "${YELLOW}Continuing with local file for apply${NC}"
fi

echo
echo -e "${BLUE}Applying Terraform changes...${NC}"
if terraform apply tfplan.binary; then
  echo -e "${GREEN}Terraform apply completed successfully${NC}"
  rm -f "$PLAN_OUTPUT_FILE" tfplan.binary
  exit 0
else
  APPLY_EXIT_CODE=$?
  echo -e "${RED}Terraform apply failed (exit code: ${APPLY_EXIT_CODE})${NC}"
  rm -f "$PLAN_OUTPUT_FILE" tfplan.binary
  exit "$APPLY_EXIT_CODE"
fi
