"""CLI entry point for the ADEPT auth proxy.

Usage::

    adept-auth-proxy --port 19283
    adept-auth-proxy --port 19283 --auth-method password --username alice --password secret
    adept-auth-proxy --upstream http://my-adept.example.com/v1
"""

from __future__ import annotations

import argparse
import logging
import sys


def main(argv: list[str] | None = None) -> None:
    """Run the ADEPT auth proxy server."""
    parser = argparse.ArgumentParser(
        prog="adept-auth-proxy",
        description=(
            "Transparent OpenAI-compatible proxy that handles ADEPT authentication. "
            "Point any OpenAI-compatible tool at http://localhost:PORT/v1."
        ),
    )

    # Connection
    parser.add_argument(
        "--upstream",
        default="http://localhost:8083/v1",
        help="ADEPT Agent Gateway URL (default: http://localhost:8083/v1)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Proxy listen address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=19283,
        help="Proxy listen port (default: 19283)",
    )

    # Authentication
    parser.add_argument(
        "--auth-method",
        choices=["api_key", "jwt", "password"],
        default="api_key",
        help="Authentication method (default: api_key)",
    )
    parser.add_argument(
        "--api-key",
        help="API key or Bearer token (for api_key/jwt auth)",
    )
    parser.add_argument(
        "--username",
        help="Keycloak username (for password auth)",
    )
    parser.add_argument(
        "--password",
        help="Keycloak password (for password auth)",
    )
    parser.add_argument(
        "--keycloak-url",
        help="Keycloak URL (for password auth; derived from upstream if unset)",
    )

    # Options
    parser.add_argument(
        "--no-verify-ssl",
        action="store_true",
        help="Disable SSL verification for upstream requests",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Request timeout in seconds (default: 300)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)",
    )

    args = parser.parse_args(argv)

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        import uvicorn
    except ImportError:
        print(
            "Error: uvicorn not installed. Install with: "
            "pip install adept-connectors[proxy]",
            file=sys.stderr,
        )
        sys.exit(1)

    from .proxy import ProxyConfig, create_proxy_app

    config = ProxyConfig(
        base_url=args.upstream,
        proxy_host=args.host,
        proxy_port=args.port,
        api_key=args.api_key,
        auth_method=args.auth_method,
        username=args.username,
        password=args.password,
        keycloak_url=args.keycloak_url,
        verify_ssl=not args.no_verify_ssl,
        request_timeout=args.timeout,
    )

    app = create_proxy_app(config)

    print(f"ADEPT Auth Proxy starting on http://{config.proxy_host}:{config.proxy_port}")
    print(f"Forwarding to: {config.base_url}")
    print(f"Auth method: {config.auth_method}")
    print(f"Configure your IDE: base_url = http://localhost:{config.proxy_port}/v1")
    print()

    uvicorn.run(app, host=config.proxy_host, port=config.proxy_port, log_level=args.log_level.lower())


if __name__ == "__main__":
    main()
