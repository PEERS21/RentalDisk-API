FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

#RUN pip install --no-cache-dir -r /srv/requirements.txt

ARG APP_PORT=4235
EXPOSE ${APP_PORT}

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
