package hubspot

import (
	"context"

	"github.com/turbot/steampipe-plugin-sdk/v5/plugin"
	"github.com/turbot/steampipe-plugin-sdk/v5/plugin/transform"
)

func Plugin(ctx context.Context) *plugin.Plugin {
	p := &plugin.Plugin{
		Name: "steampipe-plugin-hubspot",
		ConnectionConfigSchema: &plugin.ConnectionConfigSchema{
			NewInstance: ConfigInstance,
		},
		DefaultTransform: transform.FromGo().NullIfZero(),
		DefaultIgnoreConfig: &plugin.IgnoreConfig{
			ShouldIgnoreErrorFunc: shouldIgnoreErrors([]string{"404"}),
		},
		DefaultRetryConfig: &plugin.RetryConfig{
			ShouldRetryErrorFunc: shouldRetryError([]string{"429"}),
		},
		ConnectionKeyColumns: []plugin.ConnectionKeyColumn{
			{
				Name:    "portal_id",
				Hydrate: getPortalId,
			},
		},
		SchemaMode:   plugin.SchemaModeStatic,
		TableMapFunc: pluginTableDefinitions,
	}

	return p
}

func pluginTableDefinitions(ctx context.Context, d *plugin.TableMapData) (map[string]*plugin.Table, error) {

	// set Connection and ConnectionCache
	queryData := &plugin.QueryData{
		Connection:      d.Connection,
		ConnectionCache: d.ConnectionCache,
	}

	// fetch all properties of company
	companyPropertiesColumns, err := listAllPropertiesByObjectType(ctx, queryData, "company")
	if err != nil {
		plugin.Logger(ctx).Error("listAllPropertiesByObjectType", "companyPropertiesColumns", err)
		return nil, err
	}

	// fetch all properties of contact
	contactPropertiesColumns, err := listAllPropertiesByObjectType(ctx, queryData, "contact")
	if err != nil {
		plugin.Logger(ctx).Error("listAllPropertiesByObjectType", "contactPropertiesColumns", err)
		return nil, err
	}

	// fetch all properties of deal
	dealPropertiesColumns, err := listAllPropertiesByObjectType(ctx, queryData, "deal")
	if err != nil {
		plugin.Logger(ctx).Error("listAllPropertiesByObjectType", "dealPropertiesColumns", err)
		return nil, err
	}

	// fetch all properties of ticket
	ticketPropertiesColumns, err := listAllPropertiesByObjectType(ctx, queryData, "ticket")
	if err != nil {
		plugin.Logger(ctx).Error("listAllPropertiesByObjectType", "ticketPropertiesColumns", err)
		return nil, err
	}

	// Initialize tables
	tables := map[string]*plugin.Table{
		"hubspot_blog_post": tableHubSpotBlogPost(ctx),
		"hubspot_company":   tableHubSpotCompany(ctx, companyPropertiesColumns),
		"hubspot_contact":   tableHubSpotContact(ctx, contactPropertiesColumns),
		"hubspot_deal":      tableHubSpotDeal(ctx, dealPropertiesColumns),
		"hubspot_domain":    tableHubSpotDomain(ctx),
		"hubspot_hub_db":    tableHubSpotHubDB(ctx),
		"hubspot_owner":     tableHubSpotOwner(ctx),
		"hubspot_ticket":    tableHubSpotTicket(ctx, ticketPropertiesColumns),
	}

	return tables, nil
}
