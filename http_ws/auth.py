import functools

from aiohttp import web, ClientSession
from os import getenv

AUTH_SERVICE_URL = getenv("AUTH_SERVICE_URL", "http://localhost:8888/verify")


def require_auth():
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(request):
            headers = {}
            if 'Authorization' in request.headers:
                headers['Authorization'] = request.headers['Authorization']

            cookies = request.cookies

            try:
                async with ClientSession() as session:
                    async with session.get(
                            AUTH_SERVICE_URL,
                            headers=headers,
                            cookies=cookies,
                            allow_redirects=False
                    ) as resp:
                        if resp.status in (301, 302):
                            redirect_url = resp.headers.get('Location')
                            raise web.HTTPFound(location=redirect_url)

                        if resp.status != 200:
                            error_data = await resp.json()
                            return web.json_response(error_data, status=resp.status)

                        auth_info = await resp.json()
                        request['user'] = {"login": auth_info.get('user')}

            except Exception as e:
                print(e, flush=True)
                return web.json_response({'error': 'auth_service_unavailable'}, status=503)

            return await func(request)

        return wrapper

    return decorator