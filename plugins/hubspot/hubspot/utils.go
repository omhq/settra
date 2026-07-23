package hubspot

import (
	"context"
	"errors"
	"os"

	hubspot "github.com/clarkmcc/go-hubspot"
	"github.com/clarkmcc/go-hubspot/generated/v3/properties"
	"github.com/turbot/steampipe-plugin-sdk/v5/grpc/proto"
	"github.com/turbot/steampipe-plugin-sdk/v5/plugin"
)

func connect(ctx context.Context, d *plugin.QueryData) (*hubspot.TokenAuthorizer, error) {
	conn, err := connectAppTokenCached(ctx, d, nil)
	if err != nil {
		return nil, err
	}

	return conn.(*hubspot.TokenAuthorizer), nil
}

var connectAppTokenCached = plugin.HydrateFunc(connectAppTokenUncached).Memoize()

func connectAppTokenUncached(ctx context.Context, d *plugin.QueryData, _ *plugin.HydrateData) (any, error) {
	// Default to the env var settings
	appToken := os.Getenv("HUBSPOT_PRIVATE_APP_TOKEN")

	// Prefer config settings
	hubSpotConfig := GetConfig(d.Connection)
	if hubSpotConfig.PrivateAppToken != nil {
		appToken = *hubSpotConfig.PrivateAppToken
	}

	if appToken == "" {
		return nil, errors.New("'private_app_token' must be configured")
	}

	authorizer := hubspot.NewTokenAuthorizer(appToken)

	return authorizer, nil
}

func listAllPropertiesByObjectType(ctx context.Context, d *plugin.QueryData, objectType string) ([]properties.Property, error) {
	authorizer, err := connect(ctx, d)
	if err != nil {
		plugin.Logger(ctx).Error("listAllPropertiesByObjectType", "connection_error", err)
		return []properties.Property{}, nil
	}
	context := hubspot.WithAuthorizer(context.Background(), authorizer)
	client := properties.NewAPIClient(properties.NewConfiguration())
	resp, _, err := client.CoreApi.GetAll(context, objectType).Execute()
	if err != nil {
		plugin.Logger(ctx).Error("listAllPropertiesByObjectType", "api_error", err)
		return []properties.Property{}, nil
	}

	return resp.Results, nil
}

func setDynamicColumnTypes(property properties.Property, column *plugin.Column) {
	switch property.Type {
	case "string":
		column.Type = proto.ColumnType_STRING
	case "number":
		column.Type = proto.ColumnType_DOUBLE
	case "bool":
		column.Type = proto.ColumnType_BOOL
	case "datetime":
		column.Type = proto.ColumnType_TIMESTAMP
	case "enumeration":
		column.Type = proto.ColumnType_STRING
	default:
		column.Type = proto.ColumnType_STRING
	}
}
