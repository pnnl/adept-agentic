#!/bin/bash
#
# OpenAPI Documentation Generator and Validator
#
# This script validates OpenAPI specifications and optionally generates
# static HTML documentation using ReDoc.
#
# Usage:
#   ./scripts/generate-api-docs.sh [--validate-only] [--generate-html]
#
# Options:
#   --validate-only    Only validate specs, don't generate HTML
#   --generate-html    Generate static HTML documentation
#   --help            Show this help message
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
DOCS_DIR="$(pwd)/docs/api"
PUBLIC_SPEC="${DOCS_DIR}/openapi.json"
ADMIN_SPEC="${DOCS_DIR}/openapi-admin.json"
HTML_OUTPUT="${DOCS_DIR}/index.html"
ADMIN_HTML_OUTPUT="${DOCS_DIR}/admin.html"

# Flags
VALIDATE_ONLY=false
GENERATE_HTML=false

# Functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

show_help() {
    cat << EOF
OpenAPI Documentation Generator and Validator

Usage: $0 [OPTIONS]

Options:
  --validate-only     Only validate OpenAPI specs (default behavior)
  --generate-html     Generate static HTML documentation with ReDoc
  --help             Show this help message

Examples:
  # Validate specs only
  $0 --validate-only

  # Validate and generate HTML documentation
  $0 --generate-html

  # Both validation and HTML generation
  $0

EOF
}

validate_specs() {
    log_info "Validating OpenAPI specifications..."

    # Validate public API spec
    log_info "Validating public API spec: ${PUBLIC_SPEC}"
    docker run --rm -v "${DOCS_DIR}":/specs:ro python:3.11-slim /bin/bash -c \
        "pip install -q openapi-spec-validator && python -m openapi_spec_validator /specs/openapi.json" 2>&1 | grep -v "WARNING" | grep -v "notice"

    if [[ ${PIPESTATUS[0]} -eq 0 ]]; then
        log_success "Public API spec is valid ✓"
    else
        log_error "Public API spec validation failed ✗"
        return 1
    fi

    # Validate admin API spec
    log_info "Validating admin API spec: ${ADMIN_SPEC}"
    docker run --rm -v "${DOCS_DIR}":/specs:ro python:3.11-slim /bin/bash -c \
        "pip install -q openapi-spec-validator && python -m openapi_spec_validator /specs/openapi-admin.json" 2>&1 | grep -v "WARNING" | grep -v "notice"

    if [[ ${PIPESTATUS[0]} -eq 0 ]]; then
        log_success "Admin API spec is valid ✓"
    else
        log_error "Admin API spec validation failed ✗"
        return 1
    fi

    log_success "All OpenAPI specs validated successfully!"
    return 0
}

generate_html_docs() {
    log_info "Generating HTML documentation with ReDoc..."

    # Generate public API documentation
    log_info "Generating public API documentation: ${HTML_OUTPUT}"
    docker run --rm -v "${DOCS_DIR}":/specs node:18-alpine /bin/sh -c \
        "npm install -g @redocly/cli && \
         redocly build-docs /specs/openapi.json -o /specs/index.html"

    if [[ $? -eq 0 ]]; then
        log_success "Public API docs generated: ${HTML_OUTPUT} ✓"
    else
        log_error "Failed to generate public API docs ✗"
        return 1
    fi

    # Generate admin API documentation
    log_info "Generating admin API documentation: ${ADMIN_HTML_OUTPUT}"
    docker run --rm -v "${DOCS_DIR}":/specs node:18-alpine /bin/sh -c \
        "npm install -g @redocly/cli && \
         redocly build-docs /specs/openapi-admin.json -o /specs/admin.html"

    if [[ $? -eq 0 ]]; then
        log_success "Admin API docs generated: ${ADMIN_HTML_OUTPUT} ✓"
    else
        log_error "Failed to generate admin API docs ✗"
        return 1
    fi

    log_success "HTML documentation generated successfully!"
    log_info "View documentation at:"
    log_info "  - Public API: file://${HTML_OUTPUT}"
    log_info "  - Admin API:  file://${ADMIN_HTML_OUTPUT}"

    return 0
}

check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check if Docker is available
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed or not in PATH"
        exit 1
    fi

    # Check if spec files exist
    if [[ ! -f "${PUBLIC_SPEC}" ]]; then
        log_error "Public API spec not found: ${PUBLIC_SPEC}"
        exit 1
    fi

    if [[ ! -f "${ADMIN_SPEC}" ]]; then
        log_error "Admin API spec not found: ${ADMIN_SPEC}"
        exit 1
    fi

    log_success "Prerequisites check passed ✓"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --validate-only)
            VALIDATE_ONLY=true
            shift
            ;;
        --generate-html)
            GENERATE_HTML=true
            shift
            ;;
        --help)
            show_help
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# If no flags specified, default to validate only
if [[ "${VALIDATE_ONLY}" == "false" ]] && [[ "${GENERATE_HTML}" == "false" ]]; then
    VALIDATE_ONLY=true
fi

# Main execution
main() {
    echo "==========================================="
    echo "OpenAPI Documentation Generator"
    echo "==========================================="
    echo ""

    check_prerequisites
    echo ""

    # Always validate
    if ! validate_specs; then
        log_error "Validation failed. Exiting."
        exit 1
    fi

    echo ""

    # Generate HTML if requested
    if [[ "${GENERATE_HTML}" == "true" ]]; then
        if ! generate_html_docs; then
            log_error "HTML generation failed. Exiting."
            exit 1
        fi
        echo ""
    fi

    # Summary
    echo "==========================================="
    echo "Summary"
    echo "==========================================="
    log_success "Validation: ✓ Completed"
    if [[ "${GENERATE_HTML}" == "true" ]]; then
        log_success "HTML Generation: ✓ Completed"
        echo ""
        log_info "Next steps:"
        log_info "  1. Open ${HTML_OUTPUT} in a browser"
        log_info "  2. Review the generated documentation"
        log_info "  3. Host these files on a web server for team access"
    else
        log_info "Run with --generate-html to create static HTML docs"
    fi
    echo ""
}

# Run main function
main "$@"
