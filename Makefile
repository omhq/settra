IMAGE ?= omhq/settra:0.0.1
STEAMPIPE_IMAGE ?= omhq/settra-steampipe:0.0.1
CUBE_IMAGE ?= cubejs/cube:latest
STEAMPIPE_VERSION ?= 2.4.4

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
COMPOSE_ENV := IMAGE=$(IMAGE) STEAMPIPE_IMAGE=$(STEAMPIPE_IMAGE) CUBE_IMAGE=$(CUBE_IMAGE) DOCKER_DEFAULT_PLATFORM=$(LOCAL_PLATFORM)

.PHONY: dev dev-fe init install build build-steampipe publish publish-app publish-steampipe push push-steampipe pull run run-build down

dev:
	$(MAKE) -j2 dev-fe run

dev-fe:
	cd frontend && npm run dev

run:
	$(COMPOSE_ENV) docker compose up

run-build:
	$(COMPOSE_ENV) docker compose up --build

init:
	$(COMPOSE_ENV) docker compose run --rm --no-deps app python -m app.init

install:
	cd frontend && npm install
	cd backend && pip install -r requirements.txt

build:
	docker build --platform $(LOCAL_PLATFORM) --no-cache -t $(IMAGE) .

build-steampipe:
	docker build \
		--platform $(LOCAL_PLATFORM) \
		--build-arg STEAMPIPE_VERSION=$(STEAMPIPE_VERSION) \
		--no-cache \
		-f Dockerfile.steampipe \
		-t $(STEAMPIPE_IMAGE) .

publish: publish-app publish-steampipe

publish-app:
	docker buildx build \
		--platform $(PUBLISH_PLATFORMS) \
		--no-cache -t $(IMAGE) \
		--push .

publish-steampipe:
	docker buildx build \
		--platform $(PUBLISH_PLATFORMS) \
		--build-arg STEAMPIPE_VERSION=$(STEAMPIPE_VERSION) \
		--no-cache -f Dockerfile.steampipe \
		-t $(STEAMPIPE_IMAGE) \
		--push .

push: publish-app

push-steampipe: publish-steampipe

pull:
	$(COMPOSE_ENV) docker compose pull

down:
	docker compose down
