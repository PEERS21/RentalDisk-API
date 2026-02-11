FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN pip install grpcio-tools
COPY backend/qr.proto ./proto/qr.proto
RUN python -m grpc_tools.protoc -I./proto --python_out=./backend --grpc_python_out=./backend proto/qr.proto

COPY ws_server_async.py .
COPY static ./static

ENV GRPC_ADDR=api:50051
EXPOSE 8000

CMD ["python", "ws_server_async.py"]
