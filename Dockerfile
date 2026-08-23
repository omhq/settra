# Build react
FROM node:20-alpine AS frontend

ARG PRODUCT_NAME=Settra

ENV VITE_PRODUCT_NAME=${PRODUCT_NAME}

WORKDIR /app

COPY frontend/ .

RUN npm install
RUN npm run build

# Python + react static files together
FROM python:3.12-slim

WORKDIR /app

ENV STATIC_DIR=/opt/static
ENV CUBE_MODEL_DIR=/cube/conf/model

COPY backend/ .
COPY connectors/googledrive/ /config/connectors/googledrive/
COPY cube/ /cube/conf/
COPY --from=frontend /app/dist /opt/static

RUN pip install -r requirements.txt --break-system-packages

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
