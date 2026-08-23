IMAGE ?= omhq/settra:0.0.1
CUBE_IMAGE ?= cubejs/cube:latest
POSTGRES_IMAGE ?= postgres:17-alpine
PRODUCT_NAME ?= Settra

HOST_ARCH := $(shell uname -m)

ifeq ($(filter arm64 aarch64,$(HOST_ARCH)),$(HOST_ARCH))
LOCAL_PLATFORM ?= linux/arm64
else ifeq ($(filter x86_64 amd64,$(HOST_ARCH)),$(HOST_ARCH))
LOCAL_PLATFORM ?= linux/amd64
else
LOCAL_PLATFORM ?= linux/$(HOST_ARCH)
endif

DEPLOY_PLATFORM ?= linux/amd64,linux/arm64
PUBLISH_PLATFORMS ?= $(DEPLOY_PLATFORM)
COMPOSE_ENV := PRODUCT_NAME="$(PRODUCT_NAME)" IMAGE=$(IMAGE) \
	POSTGRES_IMAGE=$(POSTGRES_IMAGE) CUBE_IMAGE=$(CUBE_IMAGE) \
	DOCKER_DEFAULT_PLATFORM=$(LOCAL_PLATFORM)

.PHONY: dev dev-fe init install migrate migration build publish publish-app push pull run run-build down

dev:
	$(MAKE) -j2 dev-fe run

dev-fe:
	cd frontend && VITE_PRODUCT_NAME="$(PRODUCT_NAME)" npm run dev

run:
	$(COMPOSE_ENV) docker compose up

run-build:
	$(COMPOSE_ENV) docker compose up --build

init:
	$(COMPOSE_ENV) docker compose run --rm --no-deps app python -m app.init

migrate:
	$(COMPOSE_ENV) docker compose run --rm app alembic upgrade head

migration:
	cd backend && alembic revision -m "$(MESSAGE)"

install:
	cd frontend && npm install
	cd backend && pip install -r requirements.txt

build:
	docker build \
		--platform $(LOCAL_PLATFORM) \
		--build-arg PRODUCT_NAME="$(PRODUCT_NAME)" \
		--no-cache \
		-t $(IMAGE) .

publish: publish-app

publish-app:
	docker buildx build \
		--platform $(PUBLISH_PLATFORMS) \
		--build-arg PRODUCT_NAME="$(PRODUCT_NAME)" \
		--no-cache -t $(IMAGE) \
		--push .

push: publish-app

pull:
	$(COMPOSE_ENV) docker compose pull

down:
	docker compose down
