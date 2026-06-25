#!/bin/bash
# AWS-specific Docker build helper with rate limit mitigation
# Provides intelligent retry logic, pre-caching, and ECR pull-through support

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
MAX_RETRIES=3
RETRY_DELAY_BASE=15  # seconds (exponential: 15, 45, 135)
RETRY_DELAY=60  # seconds (legacy, unused — kept for backward compat)
USE_ECR_CACHE=${USE_ECR_CACHE:-false}
AWS_REGION=${AWS_REGION:-us-east-1}
ECR_CACHE_REGISTRY=${ECR_CACHE_REGISTRY:-""}

echo -e "${BLUE}🚀 AWS Docker Build Helper${NC}"
echo "====================================="
echo ""

# Function: Check Docker Hub rate limit
check_rate_limit() {
    echo -e "${BLUE}📊 Checking Docker Hub rate limit status...${NC}"

    if docker info 2>&1 | grep -q "Username:"; then
        echo -e "${GREEN}✅ Docker Hub: Authenticated (200 pulls/6h)${NC}"
        AUTHENTICATED=true
    else
        echo -e "${YELLOW}⚠️  Docker Hub: Anonymous (100 pulls/6h)${NC}"
        echo -e "${YELLOW}   Consider running: ./scripts/aws-docker-hub-auth.sh${NC}"
        AUTHENTICATED=false
    fi

    # Get actual rate limit status
    TOKEN=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:ratelimitpreview/test:pull" | jq -r .token 2>/dev/null || echo "")
    if [[ -n "$TOKEN" ]]; then
        RATE_LIMIT=$(curl -s --head -H "Authorization: Bearer $TOKEN" https://registry-1.docker.io/v2/ratelimitpreview/test/manifests/latest 2>/dev/null | grep -i ratelimit || echo "")
        if [[ -n "$RATE_LIMIT" ]]; then
            echo -e "${BLUE}   $RATE_LIMIT${NC}"
        fi
    fi
    echo ""
}

# Function: Pre-cache critical base images
precache_images() {
    echo -e "${YELLOW}📦 Pre-caching critical base images...${NC}"
    echo "This reduces build failures by pulling base images first"
    echo ""

    # List of critical base images from Dockerfiles
    CRITICAL_IMAGES=(
        "ubuntu:22.04"
        "postgres:15"
        "postgres:17-alpine"
        "redis:7-alpine"
        "redis/redis-stack-server:6.2.6-v19"
        "nginx:alpine"
        "python:3.11-slim"
        "python:3.11-alpine"
        "chromadb/chroma:latest"
    )

    for image in "${CRITICAL_IMAGES[@]}"; do
        echo -e "${BLUE}--> Pulling ${image}...${NC}"
        if ! docker pull "$image" 2>&1; then
            echo -e "${YELLOW}⚠️  Failed to pull ${image}, will retry during build${NC}"
        else
            echo -e "${GREEN}✅ Cached ${image}${NC}"
        fi
        sleep 2  # Rate limit friendly delay
    done
    echo ""
}

# Function: Verify Docker Hub auth endpoint is reachable (pre-flight)
verify_docker_hub_connectivity() {
    echo -e "${BLUE}🔍 Verifying Docker Hub auth endpoint connectivity...${NC}"
    local hub_attempt=1
    local hub_max=3
    local hub_delay=5

    while [[ $hub_attempt -le $hub_max ]]; do
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
            --connect-timeout 5 --max-time 10 \
            "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/ubuntu:pull" 2>/dev/null || echo "000")

        if [[ "$HTTP_CODE" == "200" ]]; then
            echo -e "${GREEN}✅ Docker Hub auth endpoint reachable (HTTP $HTTP_CODE)${NC}"
            return 0
        elif [[ "$HTTP_CODE" == "000" ]]; then
            echo -e "${YELLOW}⚠️  Docker Hub auth endpoint unreachable (attempt $hub_attempt/$hub_max)${NC}"
        else
            echo -e "${YELLOW}⚠️  Docker Hub auth endpoint returned HTTP $HTTP_CODE (attempt $hub_attempt/$hub_max)${NC}"
        fi

        if [[ $hub_attempt -lt $hub_max ]]; then
            echo -e "${YELLOW}⏳ Waiting ${hub_delay}s before retry...${NC}"
            sleep $hub_delay
            hub_delay=$((hub_delay * 2))
        fi
        hub_attempt=$((hub_attempt + 1))
    done

    echo -e "${YELLOW}⚠️  Docker Hub auth endpoint not responding after $hub_max attempts${NC}"
    echo -e "${YELLOW}   Build may fail during image pulls. Proceeding anyway.${NC}"
    return 1
}

# Function: Build with retry logic and exponential backoff
build_with_retry() {
    local build_cmd="$1"
    local attempt=1

    while [[ $attempt -le $MAX_RETRIES ]]; do
        echo -e "${BLUE}🔨 Build attempt $attempt of $MAX_RETRIES${NC}"

        if eval "$build_cmd"; then
            echo -e "${GREEN}✅ Build successful!${NC}"
            return 0
        else
            EXIT_CODE=$?
            echo -e "${RED}❌ Build failed with exit code $EXIT_CODE${NC}"

            if [[ $attempt -lt $MAX_RETRIES ]]; then
                local delay=$(( RETRY_DELAY_BASE * (3 ** (attempt - 1)) ))
                echo -e "${YELLOW}⚠️  Transient failure (exit code $EXIT_CODE)${NC}"
                echo -e "${YELLOW}⏳ Exponential backoff: waiting ${delay}s before retry...${NC}"
                sleep $delay
                attempt=$((attempt + 1))
            else
                echo -e "${RED}❌ Max retries ($MAX_RETRIES) reached. Build failed.${NC}"
                return $EXIT_CODE
            fi
        fi
    done
}

# Function: Setup ECR pull-through cache (optional)
setup_ecr_cache() {
    echo -e "${YELLOW}🔧 Setting up AWS ECR pull-through cache...${NC}"
    echo ""
    echo "This creates a pull-through cache in ECR that mirrors Docker Hub images."
    echo "Requires AWS CLI and appropriate IAM permissions."
    echo ""

    if [[ -z "$ECR_CACHE_REGISTRY" ]]; then
        echo -e "${YELLOW}⚠️  ECR_CACHE_REGISTRY not set. Skipping ECR cache setup.${NC}"
        echo "   To use ECR cache, set: export ECR_CACHE_REGISTRY='123456789012.dkr.ecr.us-east-1.amazonaws.com'"
        echo ""
        return 0
    fi

    # Check if AWS CLI is available
    if ! command -v aws &> /dev/null; then
        echo -e "${YELLOW}⚠️  AWS CLI not found. Skipping ECR cache setup.${NC}"
        return 0
    fi

    # Login to ECR
    echo -e "${BLUE}--> Logging in to ECR...${NC}"
    aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_CACHE_REGISTRY"

    if [[ $? -eq 0 ]]; then
        echo -e "${GREEN}✅ ECR authentication successful${NC}"
        echo ""
        echo -e "${BLUE}💡 To use ECR pull-through cache, update your Dockerfiles:${NC}"
        echo "   FROM nginx:alpine"
        echo "   →"
        echo "   FROM \${ECR_CACHE_REGISTRY}/ecr-public/docker/library/nginx:alpine"
        echo ""
    else
        echo -e "${YELLOW}⚠️  ECR authentication failed. Continuing without ECR cache.${NC}"
    fi
}

# Function: Show build recommendations
show_recommendations() {
    echo ""
    echo -e "${BLUE}💡 Recommendations to avoid rate limiting:${NC}"
    echo "================================================"
    echo ""
    echo "1. ${GREEN}Docker Hub Authentication${NC} (Quick Win)"
    echo "   Run: ./scripts/aws-docker-hub-auth.sh"
    echo "   Effect: 100 → 200 pulls per 6 hours"
    echo ""
    echo "2. ${GREEN}Pre-cache Images${NC} (Recommended)"
    echo "   Run: ./scripts/aws-build-helper.sh --precache"
    echo "   Effect: Reduces build failures by caching base images first"
    echo ""
    echo "3. ${GREEN}Use AWS ECR Pull-Through Cache${NC} (Best for Production)"
    echo "   Setup: https://docs.aws.amazon.com/AmazonECR/latest/userguide/pull-through-cache.html"
    echo "   Effect: Unlimited pulls from your private ECR cache"
    echo ""
    echo "4. ${GREEN}Build During Off-Peak Hours${NC}"
    echo "   Avoid: 9 AM - 5 PM UTC (peak Docker Hub usage)"
    echo "   Best: 10 PM - 6 AM UTC (lower traffic)"
    echo ""
    echo "5. ${GREEN}Use Retry Logic${NC} (Built into this script)"
    echo "   Run: ./scripts/aws-build-helper.sh --build"
    echo "   Effect: Automatically retries failed builds with backoff"
    echo ""
}

# Main execution
case "${1:-}" in
    --check)
        check_rate_limit
        ;;
    --precache)
        check_rate_limit
        precache_images
        ;;
    --setup-ecr)
        setup_ecr_cache
        ;;
    --build)
        check_rate_limit

        if [[ "$AUTHENTICATED" != "true" ]]; then
            echo -e "${YELLOW}⚠️  Recommendation: Authenticate with Docker Hub first${NC}"
            echo "   Run: ./scripts/aws-docker-hub-auth.sh"
            echo ""

            # Check if running in interactive mode
            if [[ -t 0 ]]; then
                # Interactive mode - prompt user
                read -p "Continue anyway? (y/N) " -n 1 -r
                echo
                if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                    exit 1
                fi
            else
                # Non-interactive mode - proceed with warning
                echo -e "${YELLOW}⚠️  Non-interactive mode: Proceeding without authentication${NC}"
                echo "   Build may fail due to rate limits. Authenticate before running if possible."
                echo ""
            fi
        fi

        verify_docker_hub_connectivity
        echo -e "${BLUE}🔨 Starting build with retry logic...${NC}"
        build_with_retry "make build"
        ;;
    --full)
        echo -e "${BLUE}🚀 Full AWS build workflow${NC}"
        echo "1. Check rate limit"
        echo "2. Pre-cache critical images"
        echo "3. Build with retry logic"
        echo ""

        check_rate_limit

        if [[ "$AUTHENTICATED" != "true" ]]; then
            echo -e "${YELLOW}⚠️  Docker Hub authentication recommended${NC}"
            echo "   Run: ./scripts/aws-docker-hub-auth.sh first"
            echo ""

            # Check if running in interactive mode
            if [[ -t 0 ]]; then
                # Interactive mode - prompt user
                read -p "Continue without authentication? (y/N) " -n 1 -r
                echo
                if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                    exit 1
                fi
            else
                # Non-interactive mode - proceed with warning
                echo -e "${YELLOW}⚠️  Non-interactive mode: Proceeding without authentication${NC}"
                echo "   Build may fail due to rate limits. Authenticate before running if possible."
                echo ""
            fi
        fi

        verify_docker_hub_connectivity
        precache_images
        build_with_retry "make build"
        ;;
    --help|-h|*)
        echo "Usage: $0 [OPTION]"
        echo ""
        echo "AWS-specific Docker build helper with rate limit mitigation"
        echo ""
        echo "Options:"
        echo "  --check         Check Docker Hub rate limit status"
        echo "  --precache      Pre-cache critical base images"
        echo "  --setup-ecr     Setup AWS ECR pull-through cache"
        echo "  --build         Build with automatic retry logic"
        echo "  --full          Run full workflow (check + precache + build)"
        echo "  --help, -h      Show this help message"
        echo ""
        echo "Environment Variables:"
        echo "  DOCKERHUB_USERNAME    Docker Hub username"
        echo "  DOCKERHUB_TOKEN       Docker Hub access token"
        echo "  ECR_CACHE_REGISTRY    AWS ECR registry URL (optional)"
        echo "  AWS_REGION            AWS region (default: us-east-1)"
        echo "  MAX_RETRIES           Max build retries (default: 3)"
        echo "  RETRY_DELAY           Delay between retries in seconds (default: 60)"
        echo ""
        show_recommendations
        ;;
esac
