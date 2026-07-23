package hubspot

import (
	"context"

	hubspot "github.com/clarkmcc/go-hubspot"
	"github.com/clarkmcc/go-hubspot/generated/v3/contacts"
	"github.com/clarkmcc/go-hubspot/generated/v3/properties"
	"github.com/turbot/steampipe-plugin-sdk/v5/grpc/proto"
	"github.com/turbot/steampipe-plugin-sdk/v5/plugin"
	"github.com/turbot/steampipe-plugin-sdk/v5/plugin/transform"
)

//// TABLE DEFINITION

func tableHubSpotContact(ctx context.Context, contactPropertiesColumns []properties.Property) *plugin.Table {
	return &plugin.Table{
		Name:        "hubspot_contact",
		Description: "List of HubSpot Contacts.",
		List: &plugin.ListConfig{
			Hydrate: listContacts,
			KeyColumns: []*plugin.KeyColumn{
				{
					Name:    "archived",
					Require: plugin.Optional,
				},
			},
		},
		Get: &plugin.GetConfig{
			Hydrate:    getContact,
			KeyColumns: plugin.SingleColumn("id"),
		},
		Columns: commonColumns(contactColumns(contactPropertiesColumns, []*plugin.Column{
			{
				Name:        "id",
				Type:        proto.ColumnType_STRING,
				Description: "The unique ID of the contact.",
				Transform:   transform.FromField("Id"),
			},
			{
				Name:        "created_at",
				Type:        proto.ColumnType_TIMESTAMP,
				Description: "The timestamp when the contact was created.",
			},
			{
				Name:        "updated_at",
				Type:        proto.ColumnType_TIMESTAMP,
				Description: "The timestamp when the contact was last updated.",
			},
			{
				Name:        "archived",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates whether the contact is archived or not.",
			},
			{
				Name:        "archived_at",
				Type:        proto.ColumnType_TIMESTAMP,
				Description: "The timestamp when the contact was archived.",
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

func listContacts(ctx context.Context, d *plugin.QueryData, h *plugin.HydrateData) (interface{}, error) {
		authorizer, err := connect(ctx, d)
		if err != nil {
			plugin.Logger(ctx).Error("hubspot_contact.listContacts", "connection_error", err)
			return nil, err
		}
		context := hubspot.WithAuthorizer(context.Background(), authorizer)
		client := contacts.NewAPIClient(contacts.NewConfiguration())

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
				response, _, err := client.BasicApi.GetPage(context).Limit(maxLimit).Archived(archived).Properties(d.QueryContext.Columns).Execute()
				if err != nil {
					plugin.Logger(ctx).Error("hubspot_contact.listContacts", "api_error", err)
					return nil, err
				}
				for _, contact := range response.Results {
					d.StreamListItem(ctx, contact)

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
				response, _, err := client.BasicApi.GetPage(context).Limit(maxLimit).After(after).Archived(archived).Properties(d.QueryContext.Columns).Execute()
				if err != nil {
					plugin.Logger(ctx).Error("hubspot_contact.listContacts", "api_error", err)
					return nil, err
				}
				for _, contact := range response.Results {
					d.StreamListItem(ctx, contact)

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

func getContact(ctx context.Context, d *plugin.QueryData, h *plugin.HydrateData) (interface{}, error) {
		id := d.EqualsQualString("id")

		// check if id is empty
		if id == "" {
			return nil, nil
		}

		authorizer, err := connect(ctx, d)
		if err != nil {
			plugin.Logger(ctx).Error("hubspot_contact.getContact", "connection_error", err)
			return nil, err
		}
		context := hubspot.WithAuthorizer(context.Background(), authorizer)
		client := contacts.NewAPIClient(contacts.NewConfiguration())

		contact, _, err := client.BasicApi.GetByID(context, id).Properties(d.QueryContext.Columns).Execute()
		if err != nil {
			plugin.Logger(ctx).Error("hubspot_contact.getContact", "api_error", err)
			return nil, err
		}

		return *contact, nil
}

func contactColumns(companyPropertiesColumns []properties.Property, columns []*plugin.Column) []*plugin.Column {
	return append(setContactDynamicColumns(companyPropertiesColumns), columns...)
}

func setContactDynamicColumns(properties []properties.Property) []*plugin.Column {
	Columns := []*plugin.Column{}
	for _, property := range properties {
		column := &plugin.Column{
			Name:        property.Name,
			Description: property.Description,
			Transform: transform.FromP(extractContactProperties, property.Name),
		}
		setDynamicColumnTypes(property, column)
		Columns = append(Columns, column)
	}

	return Columns
}

func extractContactProperties(_ context.Context, d *transform.TransformData) (interface{}, error) {
	ob := d.HydrateItem.(contacts.SimplePublicObjectWithAssociations).Properties
	if ob == nil {
		return nil, nil
	}
	param := d.Param.(string)
	if ob[param] == "" {
		return nil, nil
	}

	return ob[param], nil
}
