package hubspot

import (
	"github.com/turbot/steampipe-plugin-sdk/v5/plugin"
)

type hubSpotConfig struct {
	PrivateAppToken *string `hcl:"private_app_token"`
}

func ConfigInstance() interface{} {
	return &hubSpotConfig{}
}

// GetConfig :: retrieve and cast connection config from query data
func GetConfig(connection *plugin.Connection) hubSpotConfig {
	if connection == nil || connection.Config == nil {
		return hubSpotConfig{}
	}
	config, _ := connection.Config.(hubSpotConfig)
	return config
}
