# Build react
FROM node:20-alpine AS frontend

WORKDIR /app

COPY frontend/ .

RUN npm install
RUN npm run build

# Python + react static files together
FROM python:3.12-slim

WORKDIR /app

ARG MESSAGING_CHANNELS=""

ENV STATIC_DIR=/opt/static

COPY backend/ .
COPY channels/ /config/channels/
COPY prompts/ /config/prompts/
COPY models/ /config/models/
COPY connectors/ /config/connectors/
COPY --from=frontend /app/dist /opt/static

RUN pip install -r requirements.txt --break-system-packages

RUN set -eux; \
    for channel in $MESSAGING_CHANNELS; do \
        if [ -f "/config/channels/${channel}/requirements.txt" ]; then \
            pip install -r "/config/channels/${channel}/requirements.txt" --break-system-packages; \
        fi; \
    done

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
