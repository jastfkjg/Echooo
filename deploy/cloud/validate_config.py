"""Validate resolved Compose settings before stopping the running application."""
import json
import re
import sys
from urllib.parse import urlsplit


def validate(config):
    services = config["services"]
    password = services["db"]["environment"]["POSTGRES_PASSWORD"]
    if not re.fullmatch(r"[a-fA-F0-9]{64}", password):
        raise ValueError("POSTGRES_PASSWORD must be 64 hex characters; use openssl rand -hex 32.")
    app = services["app"]["environment"]
    origin = app["PUBLIC_ORIGIN"]
    url = urlsplit(origin)
    if url.scheme not in {"http", "https"} or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]*", url.netloc):
        raise ValueError("Use PUBLIC_SCHEME=http or https and a plain domain or IPv4 address in DOMAIN.")
    if origin != f"{url.scheme}://{url.netloc}":
        raise ValueError("PUBLIC_ORIGIN must be a plain origin without a path or port.")
    secure = str(app["COOKIE_SECURE"]).lower()
    if secure != ("true" if url.scheme == "https" else "false"):
        raise ValueError("Set COOKIE_SECURE=false for HTTP or true for HTTPS.")
    return origin


if __name__ == "__main__":
    try:
        print(validate(json.load(sys.stdin)))
    except (ValueError, KeyError) as exc:
        sys.exit(str(exc))
