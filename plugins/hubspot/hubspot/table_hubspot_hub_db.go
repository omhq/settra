package hubspot

import (
	"context"

	hubspot "github.com/clarkmcc/go-hubspot"
	"github.com/clarkmcc/go-hubspot/generated/v3/hubdb"
	"github.com/turbot/steampipe-plugin-sdk/v5/grpc/proto"
	"github.com/turbot/steampipe-plugin-sdk/v5/plugin"
	"github.com/turbot/steampipe-plugin-sdk/v5/plugin/transform"
)

//// TABLE DEFINITION

func tableHubSpotHubDB(ctx context.Context) *plugin.Table {
	return &plugin.Table{
		Name:        "hubspot_hub_db",
		Description: "List of HubSpot published HubDBs.",
		List: &plugin.ListConfig{
			Hydrate: listHubDBs,
			KeyColumns: []*plugin.KeyColumn{
				{
					Name:    "archived",
					Require: plugin.Optional,
				},
			},
		},
		Get: &plugin.GetConfig{
			Hydrate:    getHubDB,
			KeyColumns: plugin.SingleColumn("id"),
		},
		Columns: commonColumns([]*plugin.Column{
			{
				Name:        "id",
				Type:        proto.ColumnType_STRING,
				Description: "Id of the table.",
				Transform:   transform.FromField("Id"),
			},
			{
				Name:        "name",
				Type:        proto.ColumnType_STRING,
				Description: "Name of the table.",
			},
			{
				Name:        "label",
				Type:        proto.ColumnType_STRING,
				Description: "Label of the table.",
			},
			{
				Name:        "columns",
				Type:        proto.ColumnType_JSON,
				Description: "List of columns in the table.",
			},
			{
				Name:        "published",
				Type:        proto.ColumnType_BOOL,
				Description: "Specifies whether the table is published.",
			},
			{
				Name:        "column_count",
				Type:        proto.ColumnType_INT,
				Description: "Number of columns including deleted.",
			},
			{
				Name:        "row_count",
				Type:        proto.ColumnType_INT,
				Description: "Number of rows in the table.",
			},
			{
				Name:        "created_by",
				Type:        proto.ColumnType_JSON,
				Description: "User who created the table.",
			},
			{
				Name:        "updated_by",
				Type:        proto.ColumnType_JSON,
				Description: "User who last updated the table.",
			},
			{
				Name:        "published_at",
				Type:        proto.ColumnType_TIMESTAMP,
				Description: "Timestamp at which the table was recently published.",
			},
			{
				Name:        "dynamic_meta_tags",
				Type:        proto.ColumnType_JSON,
				Description: "Specifies the key-value pairs of metadata fields with associated column IDs.",
			},
			{
				Name:        "created_at",
				Type:        proto.ColumnType_TIMESTAMP,
				Description: "Timestamp at which the table was created.",
			},
			{
				Name:        "archived",
				Type:        proto.ColumnType_BOOL,
				Description: "Specifies whether the table is archived.",
			},
			{
				Name:        "allow_public_api_access",
				Type:        proto.ColumnType_BOOL,
				Description: "Specifies whether the table can be read by the public without authorization.",
			},
			{
				Name:        "use_for_pages",
				Type:        proto.ColumnType_BOOL,
				Description: "Specifies whether the table can be used for the creation of dynamic pages.",
			},
			{
				Name:        "enable_child_table_pages",
				Type:        proto.ColumnType_BOOL,
				Description: "Specifies the creation of multi-level dynamic pages using child tables.",
			},
			{
				Name:        "allow_child_tables",
				Type:        proto.ColumnType_BOOL,
				Description: "Specifies whether child tables can be created.",
			},
			{
				Name:        "updated_at",
				Type:        proto.ColumnType_TIMESTAMP,
				Description: "Timestamp at which the table was recently updated.",
			},

			/// Steampipe standard columns
			{
				Name:        "title",
				Description: "Title of the resource.",
				Type:        proto.ColumnType_STRING,
				Transform:   transform.FromField("Name"),
			},
		}),
	}
}

//// LIST FUNCTION

func listHubDBs(ctx context.Context, d *plugin.QueryData, h *plugin.HydrateData) (interface{}, error) {
	authorizer, err := connect(ctx, d)
	if err != nil {
		plugin.Logger(ctx).Error("hubspot_hub_db.listHubDBs", "connection_error", err)
		return nil, err
	}
	context := hubspot.WithAuthorizer(context.Background(), authorizer)
	client := hubdb.NewAPIClient(hubdb.NewConfiguration())

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
			response, _, err := client.TablesApi.GetAllTables(context).Limit(maxLimit).Archived(archived).Execute()
			if err != nil {
				plugin.Logger(ctx).Error("hubspot_hub_db.listHubDBs", "api_error", err)
				return nil, err
			}
			for _, hubPost := range response.Results {
				d.StreamListItem(ctx, hubPost)

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
			response, _, err := client.TablesApi.GetAllTables(context).Limit(maxLimit).After(after).Archived(archived).Execute()
			if err != nil {
				plugin.Logger(ctx).Error("hubspot_hub_db.listHubDBs", "api_error", err)
				return nil, err
			}
			for _, hubPost := range response.Results {
				d.StreamListItem(ctx, hubPost)

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

func getHubDB(ctx context.Context, d *plugin.QueryData, h *plugin.HydrateData) (interface{}, error) {
	id := d.EqualsQualString("id")

	// check if id is empty
	if id == "" {
		return nil, nil
	}

	authorizer, err := connect(ctx, d)
	if err != nil {
		plugin.Logger(ctx).Error("hubspot_hub_db.getHubDB", "connection_error", err)
		return nil, err
	}
	context := hubspot.WithAuthorizer(context.Background(), authorizer)
	client := hubdb.NewAPIClient(hubdb.NewConfiguration())

	hubPost, _, err := client.TablesApi.GetTableDetails(context, id).Execute()
	if err != nil {
		plugin.Logger(ctx).Error("hubspot_hub_db.getHubDB", "api_error", err)
		return nil, err
	}

	return hubPost, nil
}
