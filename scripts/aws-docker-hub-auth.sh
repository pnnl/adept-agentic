#!/bin/bash
# AWS-specific Docker Hub authentication helper
# Increases rate limit from 100 to 200 pulls per 6 hours

set -e

echo "🔐 AWS Docker Hub Authentication Helper"
echo "========================================"

# Check if Docker Hub credentials are set
if [[ -z "$DOCKERHUB_USERNAME" ]] || [[ -z "$DOCKERHUB_TOKEN" ]]; then
    echo ""
    echo "⚠️  Docker Hub credentials not found in environment"
    echo ""
    echo "To avoid rate limiting on AWS EC2, you need to authenticate with Docker Hub."
    echo ""
    echo "📋 Setup Instructions:"
    echo "1. Create a Docker Hub account (free): https://hub.docker.com/signup"
    echo "2. Generate an access token: https://hub.docker.com/settings/security"
    echo "3. Add to your environment:"
    echo ""
    echo "   export DOCKERHUB_USERNAME='your-username'"
    echo "   export DOCKERHUB_TOKEN='your-access-token'"
    echo ""
    echo "4. Re-run this script"
    echo ""
    exit 1
fi

echo "✅ Found Docker Hub credentials for user: $DOCKERHUB_USERNAME"

# Login to Docker Hub
echo "🔑 Authenticating with Docker Hub..."
echo "$DOCKERHUB_TOKEN" | docker login -u "$DOCKERHUB_USERNAME" --password-stdin

if [[ $? -eq 0 ]]; then
    echo "✅ Docker Hub authentication successful!"
    echo ""
    echo "📊 Rate Limit Status:"
    TOKEN=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:ratelimitpreview/test:pull" | jq -r .token)
    curl -s --head -H "Authorization: Bearer $TOKEN" https://registry-1.docker.io/v2/ratelimitpreview/test/manifests/latest | grep -i ratelimit
    echo ""
    echo "✅ You now have 200 pulls per 6 hours (authenticated)"
else
    echo "❌ Authentication failed. Please check your credentials."
    exit 1
fi
