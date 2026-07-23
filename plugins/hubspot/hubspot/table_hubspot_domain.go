package hubspot

import (
	"context"

	hubspot "github.com/clarkmcc/go-hubspot"
	"github.com/clarkmcc/go-hubspot/generated/v3/domains"
	"github.com/turbot/steampipe-plugin-sdk/v5/grpc/proto"
	"github.com/turbot/steampipe-plugin-sdk/v5/plugin"
	"github.com/turbot/steampipe-plugin-sdk/v5/plugin/transform"
)

//// TABLE DEFINITION

func tableHubSpotDomain(ctx context.Context) *plugin.Table {
	return &plugin.Table{
		Name:        "hubspot_domain",
		Description: "List of HubSpot Domains.",
		List: &plugin.ListConfig{
			Hydrate: listDomains,
		},
		Get: &plugin.GetConfig{
			Hydrate:    getDomain,
			KeyColumns: plugin.SingleColumn("id"),
		},
		Columns: []*plugin.Column{
			{
				Name:        "portal_id",
				Type:        proto.ColumnType_INT,
				Description: "The portal ID.",
				Hydrate:     getPortalId,
				Transform:   transform.FromValue(),
			},
			{
				Name:        "id",
				Type:        proto.ColumnType_STRING,
				Description: "The domain ID.",
				Transform:   transform.FromField("Id"),
			},
			{
				Name:        "created",
				Type:        proto.ColumnType_TIMESTAMP,
				Description: "The creation timestamp.",
			},
			{
				Name:        "updated",
				Type:        proto.ColumnType_TIMESTAMP,
				Description: "The last update timestamp.",
			},
			{
				Name:        "domain",
				Type:        proto.ColumnType_STRING,
				Description: "The domain name.",
			},
			{
				Name:        "primary_landing_page",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the domain is the primary landing page.",
			},
			{
				Name:        "primary_email",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the domain is the primary email domain.",
			},
			{
				Name:        "primary_blog",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the domain is the primary blog domain.",
			},
			{
				Name:        "primary_blog_post",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the domain is the primary domain for blog posts.",
			},
			{
				Name:        "primary_site_page",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the domain is the primary domain for site pages.",
			},
			{
				Name:        "primary_knowledge",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the domain is the primary domain for knowledge content.",
			},
			{
				Name:        "primary_legacy_page",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the domain is the primary domain for legacy pages.",
			},
			{
				Name:        "primary_click_tracking",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the domain is the primary domain for click tracking.",
			},
			{
				Name:        "full_category_key",
				Type:        proto.ColumnType_STRING,
				Description: "The full category key.",
			},
			{
				Name:        "secondary_to_domain",
				Type:        proto.ColumnType_STRING,
				Description: "The secondary domain.",
			},
			{
				Name:        "is_resolving",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the domain is resolving.",
			},
			{
				Name:        "is_dns_correct",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the DNS is configured correctly for the domain.",
			},
			{
				Name:        "manually_marked_as_resolving",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the domain was manually marked as resolving.",
			},
			{
				Name:        "consecutive_non_resolving_count",
				Type:        proto.ColumnType_INT,
				Description: "The count of consecutive non-resolving attempts.",
			},
			{
				Name:        "ssl_cname",
				Type:        proto.ColumnType_STRING,
				Description: "The SSL CNAME.",
			},
			{
				Name:        "is_ssl_enabled",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if SSL is enabled for the domain.",
			},
			{
				Name:        "is_ssl_only",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if SSL is the only option for the domain.",
			},
			{
				Name:        "certificate_id",
				Type:        proto.ColumnType_INT,
				Description: "The certificate ID.",
				Transform:   transform.FromField("CertificateId"),
			},
			{
				Name:        "ssl_request_id",
				Type:        proto.ColumnType_INT,
				Description: "The SSL request ID.",
				Transform:   transform.FromField("SslRequestId"),
			},
			{
				Name:        "is_used_for_blog_post",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the domain is used for blog posts.",
			},
			{
				Name:        "is_used_for_site_page",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the domain is used for site pages.",
			},
			{
				Name:        "is_used_for_landing_page",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the domain is used for landing pages.",
			},
			{
				Name:        "is_used_for_email",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the domain is used for email.",
			},
			{
				Name:        "is_used_for_knowledge",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the domain is used for knowledge content.",
			},
			{
				Name:        "setup_task_id",
				Type:        proto.ColumnType_INT,
				Description: "The setup task ID.",
				Transform:   transform.FromField("SetupTaskId"),
			},
			{
				Name:        "is_setup_complete",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the setup is complete for the domain.",
			},
			{
				Name:        "set_up_language",
				Type:        proto.ColumnType_STRING,
				Description: "The setup language.",
			},
			{
				Name:        "team_ids",
				Type:        proto.ColumnType_JSON,
				Description: "The team IDs associated with the domain.",
			},
			{
				Name:        "actual_cname",
				Type:        proto.ColumnType_STRING,
				Description: "The actual CNAME.",
			},
			{
				Name:        "correct_cname",
				Type:        proto.ColumnType_STRING,
				Description: "The correct CNAME.",
			},
			{
				Name:        "actual_ip",
				Type:        proto.ColumnType_STRING,
				Description: "The actual IP address.",
			},
			{
				Name:        "apex_resolution_status",
				Type:        proto.ColumnType_STRING,
				Description: "The apex resolution status.",
			},
			{
				Name:        "apex_domain",
				Type:        proto.ColumnType_STRING,
				Description: "The apex domain.",
			},
			{
				Name:        "public_suffix",
				Type:        proto.ColumnType_STRING,
				Description: "The public suffix.",
			},
			{
				Name:        "apex_ip_addresses",
				Type:        proto.ColumnType_JSON,
				Description: "The IP addresses associated with the apex domain.",
			},
			{
				Name:        "site_id",
				Type:        proto.ColumnType_INT,
				Description: "The site ID.",
				Transform:   transform.FromField("SiteId"),
			},
			{
				Name:        "brand_id",
				Type:        proto.ColumnType_INT,
				Description: "The brand ID.",
				Transform:   transform.FromField("BrandId"),
			},
			{
				Name:        "deletable",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the domain is deletable.",
			},
			{
				Name:        "domain_cdn_config",
				Type:        proto.ColumnType_JSON,
				Description: "CDN configuration for the domain.",
			},
			{
				Name:        "setup_info",
				Type:        proto.ColumnType_BOOL,
				Description: "Setup information for the domain.",
			},
			{
				Name:        "derived_brand_name",
				Type:        proto.ColumnType_STRING,
				Description: "The derived brand name.",
			},
			{
				Name:        "created_by_id",
				Type:        proto.ColumnType_INT,
				Description: "The ID of the user who created the domain.",
				Transform:   transform.FromField("CreatedById"),
			},
			{
				Name:        "updated_by_id",
				Type:        proto.ColumnType_INT,
				Description: "The ID of the user who last updated the domain.",
				Transform:   transform.FromField("UpdatedById"),
			},
			{
				Name:        "label",
				Type:        proto.ColumnType_STRING,
				Description: "The label of the domain.",
			},
			{
				Name:        "is_any_primary",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the domain is the primary domain for any content type.",
			},
			{
				Name:        "is_legacy_domain",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the domain is a legacy domain.",
			},
			{
				Name:        "is_internal_domain",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the domain is an internal domain.",
			},
			{
				Name:        "is_resolving_internal_property",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the domain is resolving an internal property.",
			},
			{
				Name:        "is_resolving_ignoring_manually_marked_as_resolving",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the domain is resolving, ignoring the manually marked flag.",
			},
			{
				Name:        "is_used_for_any_content_type",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the domain is used for any content type.",
			},
			{
				Name:        "is_legacy",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the domain is a legacy domain.",
			},
			{
				Name:        "author_at",
				Type:        proto.ColumnType_INT,
				Description: "The timestamp of the author action.",
			},
			{
				Name:        "cos_object_type",
				Type:        proto.ColumnType_STRING,
				Description: "The COS object type.",
			},
			{
				Name:        "cdn_purge_embargo_time",
				Type:        proto.ColumnType_INT,
				Description: "The CDN purge embargo time.",
			},
			{
				Name:        "is_staging_domain",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates if the domain is a staging domain.",
			},

			/// Steampipe standard columns
			{
				Name:        "title",
				Description: "Title of the resource.",
				Type:        proto.ColumnType_STRING,
				Transform:   transform.FromField("Domain"),
			},
		},
	}
}

//// LIST FUNCTION

func listDomains(ctx context.Context, d *plugin.QueryData, h *plugin.HydrateData) (interface{}, error) {
	authorizer, err := connect(ctx, d)
	if err != nil {
		plugin.Logger(ctx).Error("hubspot_domain.listDomains", "connection_error", err)
		return nil, err
	}
	context := hubspot.WithAuthorizer(context.Background(), authorizer)
	client := domains.NewAPIClient(domains.NewConfiguration())

	// Limiting the results
	var maxLimit int32 = 100
	if d.QueryContext.Limit != nil {
		limit := int32(*d.QueryContext.Limit)
		if limit < maxLimit {
			maxLimit = limit
		}
	}
	var after string = ""

	for {
		if after == "" {
			response, _, err := client.DomainsApi.GetPage(context).Limit(maxLimit).Execute()
			if err != nil {
				plugin.Logger(ctx).Error("hubspot_domain.listDomains", "api_error", err)
				return nil, err
			}
			for _, domain := range response.Results {
				d.StreamListItem(ctx, domain)

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
			response, _, err := client.DomainsApi.GetPage(context).Limit(maxLimit).After(after).Execute()
			if err != nil {
				plugin.Logger(ctx).Error("hubspot_domain.listDomains", "api_error", err)
				return nil, err
			}
			for _, domain := range response.Results {
				d.StreamListItem(ctx, domain)

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

func getDomain(ctx context.Context, d *plugin.QueryData, h *plugin.HydrateData) (interface{}, error) {
	id := d.EqualsQualString("id")

	// check if id is empty
	if id == "" {
		return nil, nil
	}

	authorizer, err := connect(ctx, d)
	if err != nil {
		plugin.Logger(ctx).Error("hubspot_domain.getDomain", "connection_error", err)
		return nil, err
	}
	context := hubspot.WithAuthorizer(context.Background(), authorizer)
	client := domains.NewAPIClient(domains.NewConfiguration())

	domain, _, err := client.DomainsApi.GetByID(context, id).Execute()
	if err != nil {
		plugin.Logger(ctx).Error("hubspot_domain.getDomain", "api_error", err)
		return nil, err
	}

	return domain, nil
}
