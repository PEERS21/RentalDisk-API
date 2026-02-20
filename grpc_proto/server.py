# api/server.py
import asyncio
import os
import tempfile
import logging
from datetime import datetime
import grpc
from sqlalchemy import select

# protobuf imports (после генерации pb-файлов)
import grpc.qr_pb2 as pb2
import grpc.qr_pb2_grpc as pb2_grpc

# async redis
import redis.asyncio as aioredis

# QR decoding
from PIL import Image
from pyzbar.pyzbar import decode as decode_qr

from common.db_init import AsyncSessionLocal
from common.db_models import Disk
from os import getenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api.server")

REDIS_URL = getenv("REDIS_URL", "redis://localhost:6379/0")
GRPC_PORT = int(getenv("GRPC_PORT", "50051"))
TEMP_DIR = getenv("TEMP_DIR", "/tmp/uploads")
os.makedirs(TEMP_DIR, exist_ok=True)
TEMP_TTL = int(getenv("TEMP_TTL", "3600"))  # seconds for temp key in redis

class qrServicer(pb2_grpc.qrServicer):
    async def UploadPhotos(self, request_iterator, context):
        """
        Асинхронно принимает stream PhotoChunk, сохраняет во временный файл,
        декодирует QR, сверяет с Redis и возвращает UploadSummary.
        """
        # создаём временный файл по user_id + message_id + filename (безопасно)
        first_chunk = True
        date_now = ""
        username = ""
        disk = ""
        received_chunks = 0

        # use NamedTemporaryFile to avoid collisions
        tmp_fd, tmp_filename = tempfile.mkstemp(prefix="upload_", suffix=".jpg", dir=TEMP_DIR)
        os.close(tmp_fd)  # we'll open by name
        try:
            with open(tmp_filename, "ab") as fh:
                async for chunk in request_iterator:
                    # extract meta from first chunk (if provided)
                    if first_chunk:
                        date_now = getattr(chunk, "date_now", "") or ""
                        username = getattr(chunk, "username", "") or ""
                        disk = getattr(chunk, "disk", "") or ""
                        first_chunk = False
                    # write bytes
                    if chunk.data:
                        fh.write(chunk.data)
                    if chunk.is_last_chunk:
                        logger.info("Received final chunk, stopping stream")
                        break 
                    received_chunks += 1

            # теперь файл сохранён
            logger.info("Received file %s from user %s, chunks=%d", tmp_filename, username, received_chunks)

            # try decode QR
            try:
                img = Image.open(tmp_filename)
                decoded = decode_qr(img)
                if decoded:
                    # take first found
                    qr_data = decoded[0].data.decode('utf-8')
                    logger.info("QR decoded: %s", qr_data)
                else:
                    qr_data = None
                    logger.info("No QR codes found")
            except Exception as e:
                logger.exception("Error decoding image")
                qr_data = None

            # connect to redis
            logger.info("connect to redis")
            redis = aioredis.from_url(REDIS_URL, decode_responses=True)
            confirmed = False
            nickname = ""
            disk_name = ""
            response_text = "QR код не распознан"
            if qr_data:
                # lookup hash -> disk mapping in Redis: key "hash:{hash}" -> disk_name
                async with AsyncSessionLocal() as session:
                    stmt = select(Disk).where(Disk.disk_hash == qr_data)
                    result = await session.execute(stmt)
                    disk_obj = result.scalars().first()
                    if not disk_obj:
                        disk_name = None
                        response_text = f"Неизвестный QR: {qr_data}"
                    else:
                        disk_name = disk_obj.name
                        response_text = disk_name
                if disk_name and disk_name == disk:
                    logger.info("confirmed")
                    confirmed = True
                    # create temporary record user->disk with TTL
                    logger.info("save confirm")
                    await redis.setex(f"check:{username}", TEMP_TTL, disk_name)
                else:
                    logger.info(f"request not confirmed: [{disk_name}] != [{disk}]")
                    confirmed = False
            else:
                logger.info(f"request not confirmed: qr data is none")
                confirmed = False
                response_text = "QR не найден на изображении"

            # build response
            logger.info(f"get iso time")
            now_iso = datetime.utcnow().isoformat() + "Z"
            logger.info(f"build response")
            response = pb2.UploadSummary(
                confirmed=confirmed,
                nickname=nickname or "",
                username=username or "",
                disk=response_text,
                datetime=now_iso,
            )
            logger.info(f"redis.close")
            await redis.aclose()
            logger.info("BEFORE RETURN UploadSummary")
            return response

        finally:
            # Удаляем временный файл (или можно оставить для отладки)
            try:
                os.remove(tmp_filename)
            except Exception:
                pass

async def serve():
    server = grpc.aio.server()
    pb2_grpc.add_qrServicer_to_server(qrServicer(), server)
    listen_addr = f"[::]:{GRPC_PORT}"
    server.add_insecure_port(listen_addr)
    logger.info("Starting gRPC server on %s", listen_addr)
    await server.start()
    await server.wait_for_termination()

if __name__ == "__main__":
    asyncio.run(serve())
