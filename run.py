"""HTTPS entrypoint.

    python run.py

Reads configuration from the environment / .env (see .env.example). Refuses to
start without TLS unless ALLOW_INSECURE_HTTP=true (for local testing or when a
TLS-terminating reverse proxy sits in front).
"""

from __future__ import annotations

import logging
import sys

import uvicorn

from app.config import get_settings


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    )
    settings = get_settings()

    if not settings.api_key_list:
        print(
            "API_KEYS is empty. Set at least one key, e.g.\n"
            "  API_KEYS=$(python -c \"import secrets;print(secrets.token_urlsafe(32))\")",
            file=sys.stderr,
        )
        return 2

    ssl_kwargs = {}
    if settings.tls_enabled:
        ssl_kwargs = {
            "ssl_certfile": settings.ssl_certfile,
            "ssl_keyfile": settings.ssl_keyfile,
        }
        if settings.ssl_keyfile_password:
            ssl_kwargs["ssl_keyfile_password"] = settings.ssl_keyfile_password.get_secret_value()
        scheme = "https"
    elif settings.allow_insecure_http:
        scheme = "http"
    else:
        print(
            "TLS is not configured. Set SSL_CERTFILE and SSL_KEYFILE "
            "(see scripts/generate_dev_cert.py), or set ALLOW_INSECURE_HTTP=true "
            "when terminating TLS in a reverse proxy.",
            file=sys.stderr,
        )
        return 2

    print(f"Serving MT5 bridge on {scheme}://{settings.host}:{settings.port}/docs")
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
        **ssl_kwargs,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
