import asyncio
import json
import logging
import os
import uuid
from typing import List

from aiohttp import web, WSMsgType, WSMessage
from redis.asyncio import Redis
from sqlalchemy import select, and_, or_

from grpc import qr_pb2 as pb2
from grpc import qr_pb2_grpc as pb2_grpc

import grpc

from sqlalchemy.orm import selectinload
import redis.asyncio as aioredis

from http_ws.auth import require_auth
from common.db_models import Item, Base, Booking, Disk, IssuedToken
from common.db_init import ENGINE, AsyncSessionLocal
from common.upload import save_uploaded_image

from aiohttp import web
from sqlalchemy import select, func
from sqlalchemy.exc import NoResultFound
from datetime import datetime, timedelta, UTC, timezone

import dateutil.parser

from dotenv import dotenv_values

from http_ws.auth import _make_hmac

config = dotenv_values(".env")

TARGET_TZ = timezone(timedelta(hours=int(config.get("TZ_OFFSET_HOURS", ""))))
MAX_BOOKING_DURATION = timedelta(hours=int(config.get("MAX_BOOKING_DURATION", "")))
MAX_BOOKING_SECONDS = int(MAX_BOOKING_DURATION.total_seconds())
BASE_DIR = os.path.dirname(__file__)
STATIC_ROOT = os.path.join(os.path.join(BASE_DIR, "http_ws"), "static")
WS_MAX_MSG_SIZE=2**26

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ws_server_async")

routes = web.RouteTableDef()

def _unauthorized(message="Unauthorized"):
    raise web.HTTPUnauthorized(
        text=message
    )

def _extract_bearer(request: web.Request) -> str:
    auth = request.headers.get("Authorization")
    if not auth:
        _unauthorized("Missing Authorization header")
    parts = auth.split()
    return parts[1]

async def authorize_request(request: web.Request):
    token = _extract_bearer(request)
    if token != config.get("AUTH_STATIC_TOKEN", ""):
        _unauthorized("Invalid token")

@routes.get("/ping")
async def ping(request):
    return web.json_response({"status": "ok"})


@routes.get("/static/{name:.*}")
async def static_files(request):
    root = config.get("STATIC_ROOT", "")
    name = request.match_info["name"]
    path = os.path.join(root, name)
    if not os.path.isfile(path):
        raise web.HTTPNotFound()
    return web.FileResponse(path)

@routes.get("/api/occupied_times")
async def occupied_times(request: web.Request):
    """
    GET params:
      - date (required): YYYY-MM-DD (interpreted as date in UTC+5)
      - disk_id (optional): integer id of disk

    Returns JSON with occupied intervals converted to UTC+5.
    """
    date_str = request.query.get("date")
    disk_id = request.query.get("disk_id")

    if not date_str:
        raise web.HTTPBadRequest(text="Missing 'date' query param in format YYYY-MM-DD")

    # Парсим дату (ожидаем YYYY-MM-DD)
    try:
        # строго форматируем date-only
        day_naive = datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        # запасной парсер — пытаемся из любой ISO-строки взять дату
        try:
            dt = dateutil.parser.parse(date_str)
            day_naive = datetime(dt.year, dt.month, dt.day)
        except Exception:
            raise web.HTTPBadRequest(text="Invalid date format. Use YYYY-MM-DD or ISO date.")

    # Интерпретируем этот день как в целевом часовом поясе (UTC+5)
    day_start_local = day_naive.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=TARGET_TZ)
    day_end_local = day_start_local + timedelta(days=1)

    # Переводим границы в UTC для запроса в базе (т.к. в БД хранится UTC)
    day_start_utc = day_start_local.astimezone(UTC)
    day_end_utc = day_end_local.astimezone(UTC)

    # Теперь выбираем брони, перекрывающие [day_start_utc, day_end_utc)
    async with AsyncSessionLocal() as session:
        overlap_condition = and_(
            Booking.start_time < day_end_utc,
            or_(Booking.end_time == None, Booking.end_time > day_start_utc)
        )
        stmt = select(Booking).where(overlap_condition)
        if disk_id:
            try:
                disk_id_int = int(disk_id)
            except ValueError:
                raise web.HTTPBadRequest(text="disk_id must be integer")
            stmt = stmt.where(Booking.disk_id == disk_id_int)

        res = await session.execute(stmt)
        bookings = res.scalars().all()

        occupied = []
        for b in bookings:
            s = b.start_time
            e = b.end_time or (b.return_time or day_end_utc)  # fallback if no end_time

            # Если в БД хранятся naive datetime (без tzinfo), считаем их UTC
            if s.tzinfo is None:
                s = s.replace(tzinfo=UTC)
            if e.tzinfo is None:
                e = e.replace(tzinfo=UTC)

            # Ограничиваем интервал границами запроса (в UTC)
            s_clipped_utc = s if s >= day_start_utc else day_start_utc
            e_clipped_utc = e if e <= day_end_utc else day_end_utc

            if s_clipped_utc < e_clipped_utc:
                # Конвертируем в целевой TZ (UTC+5) для ответа
                s_local = s_clipped_utc.astimezone(TARGET_TZ)
                e_local = e_clipped_utc.astimezone(TARGET_TZ)
                occupied.append({
                    "start": s_local.isoformat(),
                    "end": e_local.isoformat()
                })

    return web.json_response({
        "date": day_start_local.date().isoformat(),   # возвращаем дату в виде локальной даты (UTC+5)
        "disk_id": int(disk_id) if disk_id else None,
        "occupied": occupied
    })


@routes.get("/api/del_check")
@require_auth()
async def check_item(request):
    login = request.get('user', dict()).get("login")
    if not login:
        raise web.HTTPBadRequest(text="Missing query param: login")

    logger.info("connect to redis")
    redis = aioredis.from_url(config.get("REDIS_URL", ""), decode_responses=True)
    disk_name = await redis.get(f"check:{login}")
    if disk_name:
        logger.info("confirmed")
        await redis.delete(f"check:{login}")
        return web.json_response({"status": "confirmed"})
    else:
        logger.info(f"request not confirmed: [{disk_name}]")
        _unauthorized("Disk not took")

    logger.info(f"redis.close")
    await redis.aclose()
    return web.json_response({"status": "how do you do this?"})

@routes.get("/api/check")
@require_auth()
async def check_item(request):
    login = request.get('user', dict()).get("login")
    if not login:
        raise web.HTTPBadRequest(text="Missing query param: login")

    logger.info("connect to redis")
    redis = aioredis.from_url(config.get("REDIS_URL", ""), decode_responses=True)
    disk_name = await redis.get(f"check:{login}")
    if disk_name:
        logger.info("confirmed")
        return web.json_response({"status": "confirmed"})
    else:
        logger.info(f"request not confirmed: [{disk_name}]")
        _unauthorized("Disk not took")

    logger.info(f"redis.close")
    await redis.aclose()
    return web.json_response({"status": "how do you do this?"})

@routes.post("/api/block")
@require_auth()
async def block_item(request):
    data = await request.json()
    login = request.get('user', dict()).get("login")
    disk_name = data.get("disk_name")
    start_ts = data.get("start_ts")
    duration = data.get("duration_sec", int(config.get("DEFAULT_SEC_TIME", "")))

    if not login or not disk_name or not start_ts or not duration:
        raise web.HTTPBadRequest(text="Missing query param: disk_name or start_ts or duration or login")

    try:
        duration = int(duration) if duration is not None else int(config.get("DEFAULT_SEC_TIME", ""))
        if duration <= 0:
            raise ValueError
    except ValueError:
        raise web.HTTPBadRequest(text="time must be positive integer seconds")

    if duration > int(config.get("MAX_BOOKING_SECONDS", "")):
        raise web.HTTPBadRequest(text=f"duration cannot exceed {config.get("MAX_BOOKING_SECONDS", "")}")

    try:
        req_start = datetime.fromtimestamp(start_ts, tz=UTC)
        req_end = req_start + timedelta(seconds=int(duration))
    except Exception:
        raise web.HTTPBadRequest(text="Invalid time format")

    if req_start < datetime.now(UTC) - timedelta(minutes=5):
        raise web.HTTPBadRequest(text="cannot book in the past")

    ok_f = False
    status = "disk not available"

    now = datetime.now(UTC)

    async with AsyncSessionLocal() as session:
        # транзакция для защиты от гонок
        async with session.begin():
            q = select(Disk).where(Disk.name == disk_name).with_for_update()
            res = await session.execute(q)
            disk_obj = res.scalars().one_or_none()

            if disk_obj is None:
                raise web.HTTPBadRequest(text="disk not found")

            # Проверяем активную бронь на диск (если есть)
            overlap_q = select(Booking).where(
                Booking.disk_id == disk_obj.id,
                Booking.return_time == None,  # Считаем только не возвращенные
                Booking.start_time < req_end,
                Booking.end_time > req_start
            ).with_for_update()

            overlap_res = await session.execute(overlap_q)
            if overlap_res.scalars().first():
                raise web.HTTPBadRequest(text="disk already booked for this time interval")

            # Считаем текущие активные брони пользователя (не возвращённые и не истёкшие)
            cnt_q = select(func.count()).select_from(Booking).where(
                Booking.user_login == login,
                Booking.return_time == None,
                Booking.end_time > now
            )
            res_cnt = await session.execute(cnt_q)
            user_active = res_cnt.scalar_one()

            if user_active >= int(config.get("DISK_LIMIT", "")):
                status = "user reached limit"
                raise web.HTTPBadRequest(text=status)

            # Если диск помечен как доступный — продолжаем бронирование
            if disk_obj.available:
                new_booking = Booking(
                    disk_id=disk_obj.id,
                    user_login=login,
                    start_time=req_start,
                    end_time=req_end
                )

                session.add(new_booking)
                ok_f = True
                status = "confirmed"
            else:
                status = "disk not available"

    if not ok_f:
        raise web.HTTPBadRequest(text=status)
    return web.json_response({"ok": ok_f, "status": status})

async def request_confirmation(booking_id, disk, user_login):
    correlation = str(uuid.uuid4())
    payload = {
        "action": "confirm_return",
        "booking_id": booking_id,
        "disk": disk,
        "user_login": user_login,
        "requested_by": "inventory_service",
        "requested_at": datetime.now(UTC).isoformat() + "Z",
        "correlation_id": correlation
    }

    redis = aioredis.from_url(config.get("REDIS_URL", ""), decode_responses=True)
    await redis.publish("bot:requests", json.dumps(payload))

    # Опционально: ждать ответа с тайм-аутом
    psub = redis.pubsub()
    await psub.subscribe("bot:responses")
    try:
        # ждём ответа с совпадающим correlation_id
        async def waiter():
            async for msg in psub.listen():
                if msg is None or msg.get("type") != "message":
                    continue
                data = json.loads(msg["data"])
                if data.get("correlation_id") == correlation:
                    return data
            return None

        response = await asyncio.wait_for(waiter(), timeout=60.0)
    finally:
        await psub.unsubscribe("bot:responses")
        await psub.close()
        await redis.close()

    return response

@routes.get("/api/unblock")
@require_auth()
async def unblock_item(request):
    login = request.get('user', dict()).get("login")
    disk_name = request.query.get("disk")

    if not login or not disk_name:
        raise web.HTTPBadRequest(text="Missing query param: disk or login")

    ok_f = False
    status = "disk already available or invalid booking"

    now = datetime.now(UTC)

    async with AsyncSessionLocal() as session:
        async with session.begin():
            # блокируем строку диска
            q = select(Disk).where(Disk.name == disk_name).with_for_update()
            res = await session.execute(q)
            disk_obj = res.scalars().one_or_none()

            if disk_obj is None:
                raise web.HTTPBadRequest(text="disk not found")

            # ищем активную бронь для этого диска
            qb = select(Booking).where(Booking.disk_id == disk_obj.id, Booking.return_time == None).with_for_update()
            resb = await session.execute(qb)
            active_booking = resb.scalars().first()

            if active_booking and active_booking.user_login == login:
                try:
                    resp = await request_confirmation(active_booking.id, active_booking.disk, active_booking.user_login)
                except TimeoutError:
                    status = "unblock not confirmed in T-minus 60 seconds"
                if resp.get("verdict") == "accepted":
                    active_booking.return_time = now
                    session.add(active_booking)
                    ok_f = True
                    status = "confirmed"
                else:
                    status = "unblock not confirmed"
            else:
                status = "disk already available or invalid booking"

    return web.json_response({"ok": ok_f, "status": status})



@routes.get("/items")
async def list_items(request):
    async with AsyncSessionLocal() as session:
        stmt = select(Item).where(Item.available == True).order_by(Item.created_at.desc())
        result = await session.execute(stmt)
        items = result.scalars().all()
        return web.json_response([it.to_dict() for it in items])

@routes.post("/api/availability/items")
async def overwrite_availability_all(request):
    try:
        await authorize_request(request)
    except web.HTTPUnauthorized:
        raise
    async with AsyncSessionLocal() as session:
        stmt = select(Item).order_by(Item.created_at.desc())
        result = await session.execute(stmt)
        items = result.scalars().all()
        items = [it.to_dict() for it in items]
        for item in items:
            h = _make_hmac(item.get('name'))
            disk = Disk(
                name=item.get('name', "unnamed"),
                disk_hash=h,
            )
            session.add(disk)
            await session.flush()
            await session.commit()
        return web.json_response({"ok": True})

@routes.post("/api/availability/items/{id}")
async def overwrite_availability(request):
    try:
        await authorize_request(request)
    except web.HTTPUnauthorized:
        raise
    item_id = int(request.match_info["id"])
    async with AsyncSessionLocal() as session:
        stmt = select(Item).where(Item.id == item_id)
        result = await session.execute(stmt)
        it = result.scalars().first()
        if not it:
            raise web.HTTPNotFound()

        item = it.to_dict()
        h = _make_hmac(item.get('name'))
        disk = Disk(
            name=item.get('name', "unnamed"),
            disk_hash=h,
        )
        session.add(disk)
        await session.flush()
        await session.commit()
        return web.json_response({"ok": True})

@routes.delete("/api/availability/items/{name}")
async def delete_availability(request):
    try:
        await authorize_request(request)
    except web.HTTPUnauthorized:
        raise
    name = request.match_info["name"]
    async with AsyncSessionLocal() as session:
        stmt = select(Disk).where(Disk.name == name)
        result = await session.execute(stmt)
        it = result.scalars().first()
        if not it:
            raise web.HTTPNotFound()

        it.available = False
        session.add(it)
        await session.flush()
        await session.commit()
        return web.json_response({"ok": True})

@routes.get("/items/{id}")
async def get_item(request):
    item_id = int(request.match_info["id"])
    async with AsyncSessionLocal() as session:
        stmt = select(Item).where(Item.id == item_id)
        result = await session.execute(stmt)
        it = result.scalars().first()
        if not it:
            raise web.HTTPNotFound()
        return web.json_response(it.to_dict())

@routes.post("/api/items")
async def create_item(request):
    try:
        await authorize_request(request)
    except web.HTTPUnauthorized:
        raise

    reader = await request.multipart()
    data = {}
    client_img_content = None
    categories_field = None

    async for part in reader:
        if part.name == "client_img" and part.filename:
            content = await part.read()
            client_img_content = {
                'content': content,
                'filename': part.filename
            }
        else:
            val = await part.text()
            if part.name == "categories":
                categories_field = val
            else:
                data[part.name] = val

    async with AsyncSessionLocal() as session:
        item = Item(
            name=data.get("name", "unnamed"),
            company=data.get("company"),
            title=data.get("title"),
            content=data.get("content"),
        )
        session.add(item)
        await session.flush()

        cats_list: List[str] = []
        if categories_field:
            try:
                parsed = json.loads(categories_field)
                if isinstance(parsed, list):
                    cats_list = [str(x) for x in parsed]
                else:
                    cats_list = [str(categories_field)]
            except Exception:
                cats_list = [s.strip() for s in categories_field.split(",") if s.strip()]
        try:
            if cats_list:
                for c in cats_list:
                    item.categories.append(int(c))
        except TypeError:
            raise web.HTTPBadRequest(text="categories must be list of int")

        if client_img_content:
            try:
                fname2, w2, h2 = await save_uploaded_image(
                    client_img_content['content'],
                    client_img_content['filename'],
                    config.get("IMAGES_DIR", "")
                )
                item.client_img_filename = fname2
                item.client_img_height = h2
                item.client_img_width = w2
            except web.HTTPBadRequest as e:
                await session.rollback()
                raise e

        await session.commit()
        await session.refresh(item)
        await session.flush()
        return web.json_response(item.to_dict(), status=201)

@routes.delete("/api/items/{id}")
async def delete_item(request):
    try:
        await authorize_request(request)
    except web.HTTPUnauthorized:
        raise

    item_id = int(request.match_info["id"])
    async with AsyncSessionLocal() as session:
        stmt = select(Item).where(Item.id == item_id)
        result = await session.execute(stmt)
        it = result.scalars().first()
        if not it:
            raise web.HTTPNotFound()
        if it.img_filename:
            try:
                os.remove(os.path.join(config.get("IMAGES_DIR", ""), it.img_filename))
            except Exception:
                pass
        if it.client_img_filename:
            try:
                os.remove(os.path.join(config.get("IMAGES_DIR", ""), it.client_img_filename))
            except Exception:
                pass
        await session.delete(it)
        await session.commit()
        return web.json_response({"status": "deleted"})

@routes.get("/api/my_bookings")
@require_auth()
async def get_my_bookings(request):
    user_login = request['user'].get('login')
    pickupped = True if request.query.get("pickupped") == "1" else False
    if not user_login:
        return web.json_response({"error": "Unauthorized"}, status=401)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            stmt = (
                select(Booking, Disk.name)
                .join(Disk, Booking.disk_id == Disk.id)
                .where(Booking.user_login == user_login)
                .order_by(Booking.start_time.asc())
            )
            if pickupped:
                stmt = stmt.where(Booking.return_time == None)
            else:
                stmt = stmt.where(Booking.pickup_time == None)
            result = await session.execute(stmt)
            rows = result.all()

        bookings_list = []
        for booking, disk_name in rows:
            bookings_list.append({
                "id": booking.id,
                "disk_name": disk_name,
                "start_ts": int(booking.start_time.replace(tzinfo=UTC).timestamp()),
                "end_ts": int(booking.end_time.replace(tzinfo=UTC).timestamp()) if booking.end_time else None
            })

    return web.json_response(bookings_list)

@routes.get("/ws/upload")
@require_auth()
async def ws_upload(request):
    login = request.get('user', dict()).get("login")
    ws = web.WebSocketResponse(max_msg_size=WS_MAX_MSG_SIZE)
    await ws.prepare(request)
    logger.info("WebSocket connected: %s", request.remote)

    meta = None
    q: asyncio.Queue = asyncio.Queue(maxsize=WS_MAX_MSG_SIZE)
    reader_task = None
    closed_by_client = False

    async def reader():
        nonlocal meta, closed_by_client
        while True:
            msg: WSMessage = await ws.receive()
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except Exception:
                    await ws.send_str(json.dumps({"type": "error", "message": "invalid json"}))
                    continue
                t = data.get("type")
                if t == "meta":
                    meta = data
                    meta["username"] = login
                    logger.info("Received meta: %s", {k: meta.get(k) for k in ("disk","filename","username","date_now")})
                elif t == "end":
                    logger.info("Received end; finalizing queue")
                    # sentinel
                    await q.put(None)
                    # continue reading until closed
                else:
                    logger.debug("Control message: %s", data)
            elif msg.type == WSMsgType.BINARY:
                # put binary chunk into queue; will await if queue full (backpressure)
                try:
                    await q.put(msg.data)
                except asyncio.CancelledError:
                    break
            elif msg.type == WSMsgType.ERROR:
                logger.error("ws connection closed with exception %s", ws.exception())
                break
            elif msg.type == WSMsgType.CLOSE:
                logger.info("ws connection closed ")
                break
        closed_by_client = True
        # ensure generator sees end
        try:
            await q.put(None)
        except Exception:
            pass
        logger.info("Reader finished for ws %s", request.remote)

    reader_task = asyncio.create_task(reader())

    # wait meta
    for _ in range(50):  # up to ~5s
        if meta is not None:
            break
        await asyncio.sleep(0.1)
    if meta is None:
        await ws.send_str(json.dumps({"type": "error", "message": "no meta provided"}))
        reader_task.cancel()
        await ws.close()
        return ws

    stub: pb2_grpc.qrStub = request.app["grpc_stub"]

    # async generator that yields pb2.PhotoChunk
    async def grpc_gen():
        idx = 0
        if isinstance(meta, dict):
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=30)
                except asyncio.TimeoutError:
                    logger.error("Queue timeout, aborting grpc stream")
                    break
                if item is None:
                    break
                yield pb2.PhotoChunk(
                    user_id=str(meta.get("user_id", "")),
                    username=str(meta.get("username", "")),
                    filename=str(meta.get("filename", "")),
                    disk=str(meta.get("disk", "")),
                    message_id=str(meta.get("message_id", "")),
                    chunk_index=idx,
                    is_last_chunk=False,
                    data=item
                )
                idx += 1
            # final chunk marker
            yield pb2.PhotoChunk(
                user_id=str(meta.get("user_id", "")),
                username=str(meta.get("username", "")),
                filename=str(meta.get("filename", "")),
                disk=str(meta.get("disk", "")),
                message_id=str(meta.get("message_id", "")),
                chunk_index=idx,
                is_last_chunk=True,
                data=b""
            )

    # Call grpc.aio stub with async generator (client streaming)
    try:
        logger.info("Streaming to gRPC backend...")
        response = await stub.UploadPhotos(grpc_gen(), timeout=int(config.get("GRPC_TIMEOUT", "")))
        # response is pb2.UploadSummary
        is_confirmed = response.confirmed
        disk_from_qr = response.disk
        if is_confirmed:
            logger.info(f"SUCCESS: Disk {disk_from_qr} confirmed for user {login}")
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    # блокируем строку диска
                    disk_q = select(Disk).where(Disk.name == disk_from_qr).with_for_update()
                    res = await session.execute(disk_q)
                    disk_obj = res.scalars().one_or_none()

                    if disk_obj is None:
                        raise web.HTTPBadRequest(text="disk not found")

                    # ищем активную бронь для этого диска
                    qb = select(Booking).where(Booking.disk_id == disk_obj.id,
                                               Booking.pickup_time == None).with_for_update()
                    resb = await session.execute(qb)
                    now = datetime.now(UTC)
                    active_booking = resb.scalars().first()
                    active_booking.pickup_time = now
                    session.add(active_booking)
                    await session.commit()
        else:
            logger.info(f"FAILED: Confirmation failed. Server returned: {disk_from_qr}")
        resp_json = {
            "type": "result",
            "data": {
                "confirmed": response.confirmed,
                "nickname": response.nickname,
                "username": response.username,
                "disk": response.disk,
                "datetime": response.datetime,
            }
        }

        await ws.send_str(json.dumps(resp_json))
        logger.info("gRPC response sent to client")
    except asyncio.CancelledError:
        logger.info("Upload cancelled")
        try:
            reader_task.cancel()
        except Exception:
            pass
    except Exception as e:
        logger.exception("gRPC upload failed")
        await ws.send_str(json.dumps({"type": "error", "message": str(e)}))
    finally:
        if not reader_task.done():
            reader_task.cancel()
        try:
            await ws.close()
        except Exception:
            pass

    return ws

async def init_db():
    async with ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def close_engine(app):
    await ENGINE.dispose()


def make_app():
    """Создаёт aiohttp Application и регистрирует маршруты и lifecycle hooks."""
    app = web.Application(client_max_size=WS_MAX_MSG_SIZE)
    app.add_routes(routes)

    async def on_startup(app):
        logger.info("on_startup: creating grpc aio channel and stub (in running loop)")
        channel = grpc.aio.insecure_channel(config.get("GRPC_ADDR", ""))
        stub = pb2_grpc.qrStub(channel)
        app["grpc_channel"] = channel
        app["grpc_stub"] = stub
        logger.info("gRPC channel and stub created")
        await init_db()

    async def on_cleanup(app):
        logger.info("on_cleanup: closing grpc channel")
        try:
            ch = app.get("grpc_channel")
            if ch is not None:
                await ch.close()
        except Exception:
            logger.exception("Error closing grpc channel in on_cleanup")
        await close_engine(app)

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    return app

if __name__ == "__main__":
    main_frame = make_app()
    web.run_app(main_frame, host="localhost", port=int(config.get("PORT", "4235")))
