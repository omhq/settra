#!/bin/sh
set -e

container_id="$(docker ps --filter label=com.docker.compose.service=steampipe --format '{{.ID}}' | head -n 1)"

if [ -z "$container_id" ]; then
	echo "No running steampipe container found" >&2
	exit 1
fi

docker restart "$container_id"