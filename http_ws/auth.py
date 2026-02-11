import functools
from typing import Optional
from aiohttp import web
import hmac
import hashlib

from sqlalchemy import select, delete
import time

from dotenv import dotenv_values

config = dotenv_values(".env")


async def _find_token_hash(token_hash: str) -> Optional[dict]:
    from ws_server_async import AsyncSessionLocal, IssuedToken
    now = int(time.time())
    async with AsyncSessionLocal() as session:
        q = await session.execute(select(IssuedToken).where(IssuedToken.token_hash == token_hash))
        row = q.scalars().first()
        if not row:
            return None
        if row.expires_at < now:
            await session.execute(delete(IssuedToken).where(IssuedToken.token_hash == token_hash))
            await session.commit()
            return None
        return {"user": row.user_login, "issued_at": row.issued_at, "expires_at": row.expires_at}


def _make_hmac(token: str) -> str:
    return hmac.new(config.get("SECRET_KEY", "").encode('utf-8'), token.encode('utf-8'), hashlib.sha256).hexdigest()

def _extract_token_from_request(request: web.Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return request.cookies.get(config.get("COOKIE_NAME", ""))

def _forbidden_response(detail: str = "forbidden"):
    return web.json_response({"error": detail}, status=403)

def require_auth():
    """
    Декоратор
    """
    def decorator(handler):
        @functools.wraps(handler)
        async def wrapper(request: web.Request, *args, **kwargs):
            """token = _extract_token_from_request(request)

            if not token:
                return web.HTTPFound(config.get("AUTH_SERVER", "")+f"?next={request.rel_url}")

            try:
                token_hash = _make_hmac(token)
            except Exception:
                return web.HTTPFound(config.get("AUTH_SERVER", "")+f"?next={request.rel_url}")

            info = await _find_token_hash(token_hash)
            if not info:
                return web.HTTPFound(config.get("AUTH_SERVER", "")+f"?next={request.rel_url}")

            request["user"] = {"login": info["user"], "issued_at": info["issued_at"], "expires_at": info["expires_at"]}"""
            request["user"] = {"login": "tamelaos_test"}
            return await handler(request, *args, **kwargs)

        return wrapper
    return decorator
