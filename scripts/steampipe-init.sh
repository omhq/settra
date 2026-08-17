#!/bin/sh
set -e

GOOGLE_SHEETS_CONFIG_FILE="${GOOGLE_SHEETS_CONFIG_FILE:-/config/google-sheets/connection.yaml}"

plugin_installed() {
	spec="$1"

	case "$spec" in
	*@*) needle="turbot/$spec" ;;
	*) needle="turbot/$spec@latest" ;;
	esac

	steampipe plugin list | grep -F "$needle" >/dev/null 2>&1
}

ensure_plugin() {
	spec="$1"

	if plugin_installed "$spec"; then
		echo "Steampipe plugin $spec is already installed"
		return
	fi

	echo "Ensuring Steampipe plugin $spec is installed"
	steampipe plugin install --skip-config "$spec"
}

install_google_sheets_plugin() {
	if [ ! -f "$GOOGLE_SHEETS_CONFIG_FILE" ]; then
		echo "Google Sheets configuration not found at $GOOGLE_SHEETS_CONFIG_FILE" >&2
		exit 1
	fi

	set -- $(awk '
      /^plugin:[[:space:]]*/ {
        plugin = $2
      }
      /^plugin_version:[[:space:]]*/ {
        version = $2
      }
      END {
        if (plugin != "") {
          print plugin, version
        }
      }
    ' "$GOOGLE_SHEETS_CONFIG_FILE")

	if [ "${1:-}" != "googlesheets" ]; then
		echo "Only the googlesheets Steampipe plugin is supported" >&2
		exit 1
	fi

	install_plugin_pair "$1" "${2:-}"
}

install_plugin_pair() {
	plugin="$1"
	version="$2"

	if [ -z "$plugin" ]; then
		return
	fi

	if [ -n "$version" ]; then
		ensure_plugin "$plugin@${version#v}"
	else
		ensure_plugin "$plugin"
	fi
}

install_google_sheets_plugin

if [ "${STEAMPIPE_INIT_INSTALL_ONLY:-false}" = "true" ]; then
	exit 0
fi

exec steampipe service start --foreground
