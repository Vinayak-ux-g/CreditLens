#!/usr/bin/env bash
# CreditLens - Step 2 (cloud): upload raw + clean data to your own AWS S3 bucket.
#
# Prerequisites (all free):
#   1. An AWS account (Free Tier: 5 GB of S3 storage for 12 months)
#   2. AWS CLI installed:  https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
#   3. Credentials configured:  aws configure
#
# Usage:
#   chmod +x scripts/s3_upload.sh
#   ./scripts/s3_upload.sh
set -euo pipefail

BUCKET="creditlens-raw"          # must be globally unique - change if taken
REGION="ap-south-1"              # Mumbai; change to your nearest region

echo "Creating bucket s3://$BUCKET (ignored if it exists)..."
aws s3 mb "s3://$BUCKET" --region "$REGION" 2>/dev/null || echo "  bucket already exists"

echo "Uploading raw and clean datasets..."
aws s3 cp data/raw/loans_raw.csv      "s3://$BUCKET/raw/loans_raw.csv"
aws s3 cp data/clean/clean_loans.csv  "s3://$BUCKET/clean/clean_loans.csv"

echo "Verifying..."
aws s3 ls "s3://$BUCKET" --recursive

echo "Done. Screenshot this output for your README - it is the cloud step of the pipeline."
