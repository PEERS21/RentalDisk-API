import functools
from typing import Optional
from aiohttp import web
import hmac
import hashlib

from sqlalchemy import select, delete
import time
from os import getenv


def _forbidden_response(detail: str = "forbidden"):
    return web.json_response({"error": detail}, status=403)

def require_auth():
    """
    Декоратор TODO изменить на ручку /verify
    """
    def decorator(handler):
        @functools.wraps(handler)
        async def wrapper(request: web.Request, *args, **kwargs):
            """token = _extract_token_from_request(request)

            if not token:
                return web.HTTPFound(getenv("AUTH_SERVER", "")+f"?next={request.rel_url}")

            try:
                token_hash = _make_hmac(token)
            except Exception:
                return web.HTTPFound(getenv("AUTH_SERVER", "")+f"?next={request.rel_url}")

            info = await _find_token_hash(token_hash)
            if not info:
                return web.HTTPFound(getenv("AUTH_SERVER", "")+f"?next={request.rel_url}")

            request["user"] = {"login": info["user"], "issued_at": info["issued_at"], "expires_at": info["expires_at"]}"""
            request["user"] = {"login": "tamelaos_test"}
            return await handler(request, *args, **kwargs)

        return wrapper
    return decorator
