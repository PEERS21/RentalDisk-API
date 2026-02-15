FROM python:3.12-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -r requirements.txt
RUN pip install grpcio-tools
RUN pip install --no-cache-dir -r common/requirements.txt
RUN pip install --no-cache-dir -r grpc/requirements.txt

CMD ["python", "-m", "http_ws/ws_server_async"]

EXPOSE 4235