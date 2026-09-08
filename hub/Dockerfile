# Poneglyph Hub — shared server + admin GUI
# Pure stdlib; no pip install needed.
FROM python:3.12-slim

WORKDIR /app
COPY hub.py hub_db.py ./
COPY static/ ./static/

# Data lives on a mounted volume, not in the image.
ENV HUB_DB=/data/hub.db
ENV HUB_HOST=0.0.0.0
ENV HUB_PORT=8900
VOLUME ["/data"]
EXPOSE 8900

# adduser / passwd / listusers are run with `docker compose run --rm hub <cmd>`
CMD ["python", "hub.py", "serve"]
