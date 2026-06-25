"""
JupyterLab Configuration for Keycloak Integration via OAuth2 Proxy

This configuration disables JupyterLab's built-in authentication since oauth2-proxy
handles Keycloak SSO before proxying requests to JupyterLab.

Session: JupyterLab Keycloak SSO Integration (2025-01-25)
Plan: docs/implementation-plans/JUPYTERLAB_KEYCLOAK_SSO_INTEGRATION_PLAN.md
"""
import os

# Disable token and password authentication (handled by oauth2-proxy)
c.ServerApp.token = ''
c.ServerApp.password = ''

# Base URL configuration for Nginx proxy routing
c.ServerApp.base_url = os.environ.get('JUPYTER_BASE_URL', '/jupyter/')

# CORS configuration for Nginx proxy
c.ServerApp.allow_origin = '*'
c.ServerApp.allow_credentials = True

# Logging
c.Application.log_level = os.environ.get('LOGGING_LEVEL', 'INFO')

# Security headers
c.ServerApp.tornado_settings = {
    'headers': {
        'X-Frame-Options': 'SAMEORIGIN',
        'X-Content-Type-Options': 'nosniff',
    }
}
