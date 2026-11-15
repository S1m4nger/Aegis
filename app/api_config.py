"""Server-owned Go API origin and bounded, redirect-free dashboard requests."""

import ipaddress
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_API_URL = "http://127.0.0.1:8080"
API_ROUTES = frozenset({"/v1/analyze", "/v1/simulate"})
_DNS_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.?\Z")
_INVALID_CONFIGURATION = "AEGIS_API_URL must be an HTTP(S) origin without credentials, a path, query or fragment."


def validate_api_url(value):
    """Accept an operator-supplied origin, never a visitor-supplied destination."""
    if (not isinstance(value, str) or not value or "\\" in value
            or "?" in value or "#" in value
            or any(character.isspace() or ord(character) < 32 or ord(character) == 127
                   for character in value)):
        raise ValueError(_INVALID_CONFIGURATION)
    try:
        parsed = urllib.parse.urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError(_INVALID_CONFIGURATION) from None
    if (parsed.scheme not in {"http", "https"} or not parsed.netloc or not hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
            or parsed.netloc.endswith(":") or "%" in hostname
            or (port is not None and not 1 <= port <= 65535)):
        raise ValueError(_INVALID_CONFIGURATION)
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        if len(hostname) > 253 or _DNS_NAME.fullmatch(hostname) is None:
            raise ValueError(_INVALID_CONFIGURATION) from None
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def configured_api_url(environ=None):
    environment = os.environ if environ is None else environ
    return validate_api_url(environment.get("AEGIS_API_URL", DEFAULT_API_URL))


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def post_json(base, route, payload):
    """Send only known dashboard requests to the configured origin, without redirects."""
    origin = validate_api_url(base)
    if route not in API_ROUTES:
        raise ValueError("Unknown dashboard API route")
    request = urllib.request.Request(origin + route,
        data=json.dumps(payload, allow_nan=False).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        opener = urllib.request.build_opener(_NoRedirects())
        with opener.open(request, timeout=5) as response:
            content = response.read(128 * 1024 + 1)
            if len(content) > 128 * 1024:
                raise ValueError("API response exceeded the display limit")
            result = json.loads(content)
    except urllib.error.HTTPError as error:
        raise ValueError(f"Go API returned HTTP {error.code}. Check the API and model readiness.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError("Go API could not be reached. Start the Go API and trained Python scorer, then retry.") from None
    if not isinstance(result, dict):
        raise ValueError("Go API returned an invalid response")
    return result
