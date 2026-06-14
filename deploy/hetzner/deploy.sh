#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SERVER_NAME="${HCLOUD_SERVER_NAME:-settra}"
SERVER_TYPE="${HCLOUD_SERVER_TYPE:-cx23}"
SERVER_IMAGE="${HCLOUD_SERVER_IMAGE:-ubuntu-26.04}"
SERVER_LOCATION="${HCLOUD_SERVER_LOCATION:-hel1}"
SSH_KEY="${HCLOUD_SSH_KEY:-settra}"
FIREWALL_NAME="${HCLOUD_FIREWALL_NAME:-settra}"
FIREWALL_RULES_FILE="${HCLOUD_FIREWALL_RULES_FILE:-$SCRIPT_DIR/firewall-rules.json}"
SETTRA_IMAGE="${SETTRA_IMAGE:-omhq/settra:0.0.1}"
SETTRA_STEAMPIPE_IMAGE="${SETTRA_STEAMPIPE_IMAGE:-omhq/settra-steampipe:0.0.1}"
USER_DATA_FILE=""

cleanup() {
	if [ -n "$USER_DATA_FILE" ]; then
		rm -f "$USER_DATA_FILE"
	fi
}

trap cleanup EXIT

require_hcloud() {
	if ! command -v hcloud >/dev/null 2>&1; then
		echo "hcloud CLI is required. Install it and run 'hcloud context create <context-name>' first." >&2
		exit 1
	fi
}

resource_exists() {
	local resource_type="$1"
	local resource_name="$2"
	local output

	if output="$(hcloud "$resource_type" describe "$resource_name" 2>&1)"; then
		return 0
	fi

	if printf '%s\n' "$output" | grep -qi "not found"; then
		return 1
	fi

	printf '%s\n' "$output" >&2
	exit 1
}

require_hcloud

USER_DATA_FILE="$(mktemp)"
settra_image_sed="$(printf '%s' "$SETTRA_IMAGE" | sed 's/[&|]/\\&/g')"
settra_steampipe_image_sed="$(printf '%s' "$SETTRA_STEAMPIPE_IMAGE" | sed 's/[&|]/\\&/g')"
sed \
	-e "s|omhq/settra:0.0.1|$settra_image_sed|g" \
	-e "s|omhq/settra-steampipe:0.0.1|$settra_steampipe_image_sed|g" \
	"$SCRIPT_DIR/cloud-init.yml" > "$USER_DATA_FILE"

if resource_exists server "$SERVER_NAME"; then
	echo "Server '$SERVER_NAME' already exists." >&2
	echo "Delete it first with: hcloud server delete '$SERVER_NAME'" >&2
	exit 1
fi

if resource_exists firewall "$FIREWALL_NAME"; then
	echo "Updating firewall '$FIREWALL_NAME' from $FIREWALL_RULES_FILE"
	hcloud firewall replace-rules --rules-file "$FIREWALL_RULES_FILE" "$FIREWALL_NAME"
else
	echo "Creating firewall '$FIREWALL_NAME' from $FIREWALL_RULES_FILE"
	hcloud firewall create \
		--name "$FIREWALL_NAME" \
		--label app=settra \
		--label managed-by=settra \
		--rules-file "$FIREWALL_RULES_FILE"
fi

hcloud server create \
	--name "$SERVER_NAME" \
	--type "$SERVER_TYPE" \
	--image "$SERVER_IMAGE" \
	--location "$SERVER_LOCATION" \
	--ssh-key "$SSH_KEY" \
	--firewall "$FIREWALL_NAME" \
	--label app=settra \
	--label managed-by=settra \
	--user-data-from-file "$USER_DATA_FILE"
