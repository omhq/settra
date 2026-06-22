# Build react
FROM node:20-alpine AS frontend

WORKDIR /app

COPY frontend/ .

RUN npm install
RUN npm run build

# Python + react static files together
FROM python:3.12-slim

WORKDIR /app

ENV STATIC_DIR=/opt/static

COPY backend/ .
COPY prompts/ /config/prompts/
COPY models/ /config/models/
COPY connectors/ /config/connectors/
COPY --from=frontend /app/dist /opt/static

RUN apt-get update && apt-get install -y --no-install-recommends docker.io && rm -rf /var/lib/apt/lists/*

COPY scripts/restart-steampipe.sh /usr/local/bin/restart-steampipe.sh

RUN chmod +x /usr/local/bin/restart-steampipe.sh

RUN pip install -r requirements.txt --break-system-packages

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
