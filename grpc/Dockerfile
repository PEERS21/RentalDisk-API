FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Генерация pb2-файлов
COPY proto/qr.proto proto/qr.proto
RUN python -m grpc_tools.protoc -I./proto --python_out=. --grpc_python_out=. proto/qr.proto
COPY server.py .
CMD ["python", "server.py"]
