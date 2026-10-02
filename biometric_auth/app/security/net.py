"""Client IP resolution.

``X-Forwarded-For`` is set by the client, so it is only believed when the
direct peer is a proxy listed in ``TRUSTED_PROXIES``. Otherwise anyone could
pick their own IP and dodge rate limits or the risk engine's IP-change signal.
"""

from starlette.requests import Request

from app.config import settings


def get_client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    if peer in settings.trusted_proxies:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return peer
