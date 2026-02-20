FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

RUN git clone https://github.com/PEERS21/Common-python.git /app/common

RUN pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r http_ws/requirements.txt -r common/requirements.txt -r grpc_proto/requirements.txt \
 && pip uninstall -y redis || true \
 && pip install --no-cache-dir "redis==7.2.0"
RUN pip install grpcio-tools

CMD ["python", "-m", "http_ws.ws_server_async"]

EXPOSE 4235
