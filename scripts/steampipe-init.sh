#!/bin/sh
set -e

CONNECTORS_DIR="${CONNECTORS_DIR:-/config/connectors}"

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

install_declared_plugins() {
	if [ ! -d "$CONNECTORS_DIR" ]; then
		echo "No connectors directory found at $CONNECTORS_DIR; skipping plugin install"
		return
	fi

	for connection_file in "$CONNECTORS_DIR"/*/connection.yaml "$CONNECTORS_DIR"/*/connection.yml; do
		if [ ! -f "$connection_file" ]; then
			continue
		fi

		awk '
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
    ' "$connection_file"
	done | while read -r plugin version; do
		install_plugin_pair "$plugin" "$version"
	done
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

install_declared_plugins

if [ "${STEAMPIPE_INIT_INSTALL_ONLY:-false}" = "true" ]; then
	exit 0
fi

exec steampipe service start --foreground
