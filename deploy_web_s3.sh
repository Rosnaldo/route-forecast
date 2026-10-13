#!/bin/bash
# Build the React frontend and publish it to an S3 static website.
#
# The build reads GOOGLE_MAPS_API_KEY from the repo-root .env (frontend/vite.config.js)
# and bakes it into the bundle: the key's HTTP-referrer restriction must allow the
# site's URL. Needs Node (npm) and the AWS CLI with credentials for the bucket.
set -euo pipefail

BUCKET_NAME="nanithefuck-website"      # Replace with your bucket name
REGION="sa-east-1"                     # AWS region of your bucket
DISTRIBUTION_ID="E2O3MSIS2NJ6RS"        # CloudFront in front of the bucket
SITE_URL="https://d1bg1gulylxih6.cloudfront.net"

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
BUILD_DIR="$FRONTEND_DIR/dist"         # Vite's output

# ===============================
# BUILD
# ===============================

echo "Building the frontend..."
npm ci --prefix "$FRONTEND_DIR" --no-audit --no-fund
npm run build --prefix "$FRONTEND_DIR"

# ===============================
# DEPLOYMENT
# ===============================

echo "Starting deployment to S3 bucket: $BUCKET_NAME"

# Assets first: their names carry a content hash, so they never change and can be
# cached for good; uploading them before index.html means the new page never points at
# files that are not there yet. --delete removes files from older builds.
aws s3 sync "$BUILD_DIR" "s3://$BUCKET_NAME/" \
    --region "$REGION" \
    --exclude "index.html" \
    --cache-control "public, max-age=31536000, immutable" \
    --delete

# index.html last, never cached: browsers always get the page naming the newest assets.
aws s3 cp "$BUILD_DIR/index.html" "s3://$BUCKET_NAME/index.html" \
    --region "$REGION" \
    --cache-control "no-cache, no-store, must-revalidate"

# CloudFront may still hold the previous index.html at its edges: drop it. Assets need
# no invalidation, their names change with their content.
echo "Invalidating the CloudFront copy of index.html..."
aws cloudfront create-invalidation \
    --distribution-id "$DISTRIBUTION_ID" \
    --paths "/" "/index.html" \
    --query "Invalidation.Id" --output text

echo "Deployment completed!"
echo "Your site should be live at: $SITE_URL/"
