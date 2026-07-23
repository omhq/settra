package hubspot

import (
	"context"

	hubspot "github.com/clarkmcc/go-hubspot"
	"github.com/clarkmcc/go-hubspot/generated/v3/deals"
	"github.com/clarkmcc/go-hubspot/generated/v3/properties"
	"github.com/turbot/steampipe-plugin-sdk/v5/grpc/proto"
	"github.com/turbot/steampipe-plugin-sdk/v5/plugin"
	"github.com/turbot/steampipe-plugin-sdk/v5/plugin/transform"
)

//// TABLE DEFINITION

func tableHubSpotDeal(ctx context.Context, dealPropertiesColumns []properties.Property) *plugin.Table {
	return &plugin.Table{
		Name:        "hubspot_deal",
		Description: "List of HubSpot Deals.",
		List: &plugin.ListConfig{
			Hydrate: listDeals,
			KeyColumns: []*plugin.KeyColumn{
				{
					Name:    "archived",
					Require: plugin.Optional,
				},
			},
		},
		Get: &plugin.GetConfig{
			Hydrate:    getDeal,
			KeyColumns: plugin.SingleColumn("id"),
		},
		Columns: commonColumns(dealColumns(dealPropertiesColumns, []*plugin.Column{
			{
				Name:        "primary_company_id",
				Type:        proto.ColumnType_STRING,
				Description: "The ID of the company associated to the deal as its primary company.",
				Transform:   transform.FromP(extractDealProperties, "primary_company_id"),
			},
			{
				Name:        "id",
				Type:        proto.ColumnType_STRING,
				Description: "The unique ID of the deal.",
				Transform:   transform.FromField("Id"),
			},
			{
				Name:        "created_at",
				Type:        proto.ColumnType_TIMESTAMP,
				Description: "The timestamp when the deal was created.",
			},
			{
				Name:        "updated_at",
				Type:        proto.ColumnType_TIMESTAMP,
				Description: "The timestamp when the deal was last updated.",
			},
			{
				Name:        "archived",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates whether the deal is archived or not.",
			},
			{
				Name:        "archived_at",
				Type:        proto.ColumnType_TIMESTAMP,
				Description: "The timestamp when the deal was archived.",
			},

			/// Steampipe standard columns
			{
				Name:        "title",
				Description: "Title of the resource.",
				Type:        proto.ColumnType_STRING,
				Transform:   transform.FromField("Id"),
			},
		})),
	}
}

//// LIST FUNCTION

func listDeals(ctx context.Context, d *plugin.QueryData, h *plugin.HydrateData) (interface{}, error) {
	authorizer, err := connect(ctx, d)
	if err != nil {
		plugin.Logger(ctx).Error("hubspot_deal.listDeals", "connection_error", err)
		return nil, err
	}
	context := hubspot.WithAuthorizer(context.Background(), authorizer)
	client := deals.NewAPIClient(deals.NewConfiguration())

	// Limiting the results
	var maxLimit int32 = 100
	if d.QueryContext.Limit != nil {
		limit := int32(*d.QueryContext.Limit)
		if limit < maxLimit {
			maxLimit = limit
		}
	}
	var after string = ""
	archived := false

	if d.EqualsQuals["archived"] != nil {
		archived = d.EqualsQuals["archived"].GetBoolValue()
	}

	for {
		if after == "" {
			response, _, err := client.BasicApi.GetPage(context).Limit(maxLimit).Archived(archived).Properties(d.QueryContext.Columns).Associations([]string{"companies"}).Execute()
			if err != nil {
				plugin.Logger(ctx).Error("hubspot_deal.listDeals", "api_error", err)
				return nil, err
			}
			for _, deal := range response.Results {
				setPrimaryCompanyID(&deal)
				d.StreamListItem(ctx, deal)

				// Context can be cancelled due to manual cancellation or the limit has been hit
				if d.RowsRemaining(ctx) == 0 {
					return nil, nil
				}
			}
			if !response.Paging.HasNext() {
				break
			}
			after = response.Paging.Next.After
		} else {
			response, _, err := client.BasicApi.GetPage(context).Limit(maxLimit).After(after).Archived(archived).Properties(d.QueryContext.Columns).Associations([]string{"companies"}).Execute()
			if err != nil {
				plugin.Logger(ctx).Error("hubspot_deal.listDeals", "api_error", err)
				return nil, err
			}
			for _, deal := range response.Results {
				setPrimaryCompanyID(&deal)
				d.StreamListItem(ctx, deal)

				// Context can be cancelled due to manual cancellation or the limit has been hit
				if d.RowsRemaining(ctx) == 0 {
					return nil, nil
				}
			}
			if !response.Paging.HasNext() {
				break
			}
			after = response.Paging.Next.After
		}
	}

	return nil, nil
}

//// HYDRATE FUNCTIONS

func getDeal(ctx context.Context, d *plugin.QueryData, h *plugin.HydrateData) (interface{}, error) {
	id := d.EqualsQualString("id")

	// check if id is empty
	if id == "" {
		return nil, nil
	}

	authorizer, err := connect(ctx, d)
	if err != nil {
		plugin.Logger(ctx).Error("hubspot_deal.getDeal", "connection_error", err)
		return nil, err
	}
	context := hubspot.WithAuthorizer(context.Background(), authorizer)
	client := deals.NewAPIClient(deals.NewConfiguration())

	deal, _, err := client.BasicApi.GetByID(context, id).Properties(d.QueryContext.Columns).Associations([]string{"companies"}).Execute()
	if err != nil {
		plugin.Logger(ctx).Error("hubspot_deal.getDeal", "api_error", err)
		return nil, err
	}

	setPrimaryCompanyID(deal)
	return deal, nil
}

func setPrimaryCompanyID(deal *deals.SimplePublicObjectWithAssociations) {
	if deal == nil {
		return
	}
	if deal.Properties == nil {
		deal.Properties = map[string]string{}
	}
	if companyID := primaryCompanyID(*deal); companyID != "" {
		deal.Properties["primary_company_id"] = companyID
	}
}

func primaryCompanyID(deal deals.SimplePublicObjectWithAssociations) string {
	associations, ok := deal.GetAssociationsOk()
	if !ok {
		return ""
	}
	companies, ok := (*associations)["companies"]
	if !ok {
		return ""
	}
	for _, company := range companies.Results {
		if company.Type == "deal_to_company" || company.Type == "deal_to_primary_company" {
			return company.Id
		}
	}
	return ""
}

func dealColumns(dealPropertiesColumns []properties.Property, columns []*plugin.Column) []*plugin.Column {
	return append(setDealDynamicColumns(dealPropertiesColumns), columns...)
}

func setDealDynamicColumns(properties []properties.Property) []*plugin.Column {
	Columns := []*plugin.Column{}
	for _, property := range properties {
		column := &plugin.Column{
			Name:        property.Name,
			Description: property.Description,
			Transform:   transform.FromP(extractDealProperties, property.Name),
		}
		setDynamicColumnTypes(property, column)
		Columns = append(Columns, column)
	}

	return Columns
}

func extractDealProperties(_ context.Context, d *transform.TransformData) (interface{}, error) {
	ob := d.HydrateItem.(deals.SimplePublicObjectWithAssociations).Properties
	if ob == nil {
		return nil, nil
	}
	param := d.Param.(string)
	if ob[param] == "" {
		return nil, nil
	}

	return ob[param], nil
}
