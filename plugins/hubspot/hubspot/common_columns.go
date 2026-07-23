package hubspot

import (
	"context"
	"encoding/json"
	"io"
	"net/http"

	"github.com/turbot/steampipe-plugin-sdk/v5/grpc/proto"
	"github.com/turbot/steampipe-plugin-sdk/v5/memoize"
	"github.com/turbot/steampipe-plugin-sdk/v5/plugin"
	"github.com/turbot/steampipe-plugin-sdk/v5/plugin/transform"
)

func commonColumns(c []*plugin.Column) []*plugin.Column {
	return append([]*plugin.Column{
		{
			Name:        "portal_id",
			Description: "Unique identifier for the HubSpot portal or account.",
			Type:        proto.ColumnType_STRING,
			Hydrate:     getPortalId,
			Transform:   transform.FromValue(),
		},
	}, c...)
}

// if the caching is required other than per connection, build a cache key for the call and use it in Memoize.
var getPortalIdMemoized = plugin.HydrateFunc(getPortalInfoUncached).Memoize(memoize.WithCacheKeyFunction(getPortalIdCacheKey))

// declare a wrapper hydrate function to call the memoized function
// - this is required when a memoized function is used for a column definition
func getPortalId(ctx context.Context, d *plugin.QueryData, h *plugin.HydrateData) (interface{}, error) {
	acc, err := getPortalIdMemoized(ctx, d, h)
	if err != nil {
		return nil, err
	}

	return acc.(AccountInfo).PortalID, nil
}

// Build a cache key for the call to getPortalIdCacheKey.
func getPortalIdCacheKey(ctx context.Context, d *plugin.QueryData, h *plugin.HydrateData) (interface{}, error) {
	key := "getPortalId"
	return key, nil
}

func getPortalInfoUncached(ctx context.Context, d *plugin.QueryData, h *plugin.HydrateData) (interface{}, error) {
	authorizer, err := connect(ctx, d)
	if err != nil {
		plugin.Logger(ctx).Error("getPortalIdUncached", "connection_error", err)
		return nil, err
	}

	// Create a new HTTP client
	client := &http.Client{}

	url := "https://api.hubapi.com/account-info/v3/details"

	// Create a new HTTP request
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		plugin.Logger(ctx).Error("getPortalIdUncached.NewRequestWithContext", err)
		return nil, err
	}

	// Add authorization header to the request
	req.Header.Add("Authorization", "Bearer "+authorizer.Token)

	// Send the request and get a response
	resp, err := client.Do(req)
	if err != nil {
		plugin.Logger(ctx).Error("getPortalIdUncached", "failed to send request", err)
		return nil, err
	}
	defer resp.Body.Close() // Close the response body on the function return

	// Read the response body
	responseBody, err := io.ReadAll(resp.Body)
	if err != nil {
		plugin.Logger(ctx).Error("getPortalIdUncached", "Failed to read response body", err)
		return nil, err
	}

	var accInfo AccountInfo
	if err := json.Unmarshal(responseBody, &accInfo); err != nil {
		plugin.Logger(ctx).Error("getPortalIdUncached", "Error unmarshalling JSON", err)
		return nil, err
	}

	return accInfo, nil
}

type AccountInfo struct {
	PortalID              int64    `json:"portalId"`
	AccountType           string   `json:"accountType"`
	TimeZone              string   `json:"timeZone"`
	CompanyCurrency       string   `json:"companyCurrency"`
	AdditionalCurrencies  []string `json:"additionalCurrencies"`
	UTCOffset             string   `json:"utcOffset"`
	UTCOffsetMilliseconds int64    `json:"utcOffsetMilliseconds"`
	UIDomain              string   `json:"uiDomain"`
	DataHostingLocation   string   `json:"dataHostingLocation"`
}
