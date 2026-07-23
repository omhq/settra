package hubspot

import (
	"context"

	hubspot "github.com/clarkmcc/go-hubspot"
	"github.com/clarkmcc/go-hubspot/generated/v3/blog_posts"
	"github.com/turbot/steampipe-plugin-sdk/v5/grpc/proto"
	"github.com/turbot/steampipe-plugin-sdk/v5/plugin"
	"github.com/turbot/steampipe-plugin-sdk/v5/plugin/transform"
)

//// TABLE DEFINITION

func tableHubSpotBlogPost(ctx context.Context) *plugin.Table {
	return &plugin.Table{
		Name:        "hubspot_blog_post",
		Description: "List of HubSpot BlogPosts.",
		List: &plugin.ListConfig{
			Hydrate: listBlogPosts,
			KeyColumns: []*plugin.KeyColumn{
				{
					Name:    "archived",
					Require: plugin.Optional,
				},
			},
		},
		Get: &plugin.GetConfig{
			Hydrate:    getBlogPost,
			KeyColumns: plugin.SingleColumn("id"),
		},
		Columns: commonColumns([]*plugin.Column{
			{
				Name:        "id",
				Type:        proto.ColumnType_STRING,
				Description: "The unique ID of the Blog Post.",
				Transform:   transform.FromField("Id"),
				//Transform function has been used in many places across the tables to fetch the values returned by the API. Without the transform function we are getting empty row.
			},
			{
				Name:        "slug",
				Type:        proto.ColumnType_STRING,
				Description: "The path of the this blog post. This field is appended to the domain to construct the url of this post.",
			},
			{
				Name:        "content_group_id",
				Type:        proto.ColumnType_STRING,
				Description: "The ID of the parent Blog this Blog Post is associated with.",
				Transform:   transform.FromField("ContentGroupId"),
			},
			{
				Name:        "campaign",
				Type:        proto.ColumnType_STRING,
				Description: "The GUID of the marketing campaign this Blog Post is a part of.",
			},
			{
				Name:        "category_id",
				Type:        proto.ColumnType_INT,
				Description: "ID of the category.",
				Transform:   transform.FromField("CategoryId"),
			},
			{
				Name:        "state",
				Type:        proto.ColumnType_STRING,
				Description: "An ENUM describing the current state of this Blog Post.",
			},
			{
				Name:        "name",
				Type:        proto.ColumnType_STRING,
				Description: "The internal name of the Blog Post.",
			},
			{
				Name:        "mab_experiment_id",
				Type:        proto.ColumnType_STRING,
				Description: "The ID of the MAB (Multi-Armed Bandit) experiment this Blog Post is associated with.",
				Transform:   transform.FromField("MabExperimentId"),
			},
			{
				Name:        "archived",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates whether the blog post is archived or not.",
			},
			{
				Name:        "author_name",
				Type:        proto.ColumnType_STRING,
				Description: "The name of the user that updated this Blog Post.",
			},
			{
				Name:        "ab_test_id",
				Type:        proto.ColumnType_STRING,
				Description: "The ID of the A/B test this Blog Post is associated with.",
				Transform:   transform.FromField("AbTestId"),
			},
			{
				Name:        "created_by_id",
				Type:        proto.ColumnType_STRING,
				Description: "The ID of the user that created this Blog Post.",
				Transform:   transform.FromField("CreatedById"),
			},
			{
				Name:        "updated_by_id",
				Type:        proto.ColumnType_STRING,
				Description: "The ID of the user that updated this Blog Post.",
				Transform:   transform.FromField("UpdatedById"),
			},
			{
				Name:        "domain",
				Type:        proto.ColumnType_STRING,
				Description: "The domain this Blog Post will resolve to. If null, the Blog Post will default to the domain of the ParentBlog.",
			},
			{
				Name:        "ab_status",
				Type:        proto.ColumnType_STRING,
				Description: "The AB status.",
			},
			{
				Name:        "folder_id",
				Type:        proto.ColumnType_STRING,
				Description: "The folder ID.",
				Transform:   transform.FromField("FolderId"),
			},
			{
				Name:        "widget_containers",
				Type:        proto.ColumnType_JSON,
				Description: "A data structure containing the data for all the modules inside the containers for this post. This will only be populated if the page has widget containers.",
			},
			{
				Name:        "widgets",
				Type:        proto.ColumnType_JSON,
				Description: "A data structure containing the data for all the modules for this page.",
			},
			{
				Name:        "language",
				Type:        proto.ColumnType_STRING,
				Description: "The explicitly defined ISO 639 language code of the Blog Post. If null, the Blog Post will default to the language of the ParentBlog.",
			},
			{
				Name:        "translated_from_id",
				Type:        proto.ColumnType_STRING,
				Description: "ID of the primary blog post this object was translated from.",
				Transform:   transform.FromField("TranslatedFromId"),
			},
			{
				Name:        "translations",
				Type:        proto.ColumnType_JSON,
				Description: "Map of translations for this Blog Post.",
			},
			{
				Name:        "dynamic_page_data_source_type",
				Type:        proto.ColumnType_INT,
				Description: "The type of dynamic data source for the page.",
			},
			{
				Name:        "dynamic_page_data_source_id",
				Type:        proto.ColumnType_STRING,
				Description: "The ID of the dynamic data source for the page.",
				Transform:   transform.FromField("DynamicPageDataSourceId"),
			},
			{
				Name:        "blog_author_id",
				Type:        proto.ColumnType_STRING,
				Description: "The ID of the Blog Author associated with this Blog Post.",
				Transform:   transform.FromField("BlogAuthorId"),
			},
			{
				Name:        "tag_ids",
				Type:        proto.ColumnType_JSON,
				Description: "List of IDs for the tags associated with this Blog Post.",
			},
			{
				Name:        "html_title",
				Type:        proto.ColumnType_STRING,
				Description: "The HTML title of this Blog Post.",
			},
			{
				Name:        "enable_google_amp_output_override",
				Type:        proto.ColumnType_BOOL,
				Description: "Boolean to allow overriding the AMP settings for the blog.",
			},
			{
				Name:        "use_featured_image",
				Type:        proto.ColumnType_BOOL,
				Description: "Boolean to determine if this post should use a featured image.",
			},
			{
				Name:        "post_body",
				Type:        proto.ColumnType_STRING,
				Description: "The HTML of the main post body.",
			},
			{
				Name:        "post_summary",
				Type:        proto.ColumnType_STRING,
				Description: "The summary of the blog post that will appear on the main listing page.",
			},
			{
				Name:        "rss_body",
				Type:        proto.ColumnType_STRING,
				Description: "The contents of the RSS body for this Blog Post.",
			},
			{
				Name:        "rss_summary",
				Type:        proto.ColumnType_STRING,
				Description: "The contents of the RSS summary for this Blog Post.",
			},
			{
				Name:        "currently_published",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates whether the blog post is currently published or not.",
			},
			{
				Name:        "page_expiry_enabled",
				Type:        proto.ColumnType_BOOL,
				Description: "Indicates whether the page expiry is enabled or not.",
			},
			{
				Name:        "page_expiry_redirect_id",
				Type:        proto.ColumnType_INT,
				Description: "The ID of the page to redirect to upon expiry.",
				Transform:   transform.FromField("PageExpiryRedirectId"),
			},
			{
				Name:        "page_expiry_redirect_url",
				Type:        proto.ColumnType_STRING,
				Description: "The URL to redirect to upon expiry.",
			},
			{
				Name:        "page_expiry_date",
				Type:        proto.ColumnType_INT,
				Description: "The expiry date of the page.",
			},
			{
				Name:        "include_default_custom_css",
				Type:        proto.ColumnType_BOOL,
				Description: "Boolean to determine whether or not to apply the Primary CSS Files.",
			},
			{
				Name:        "enable_layout_stylesheets",
				Type:        proto.ColumnType_BOOL,
				Description: "Boolean to determine whether or not to apply the styles from the template.",
			},
			{
				Name:        "enable_domain_stylesheets",
				Type:        proto.ColumnType_BOOL,
				Description: "Boolean to determine whether or not to apply the styles from the template.",
			},
			{
				Name:        "publish_immediately",
				Type:        proto.ColumnType_BOOL,
				Description: "Set this to true if you want to be published immediately when the schedule publish endpoint is called, and to ignore the publish_date setting.",
			},
			{
				Name:        "featured_image",
				Type:        proto.ColumnType_STRING,
				Description: "The featured image of this Blog Post.",
			},
			{
				Name:        "featured_image_alt_text",
				Type:        proto.ColumnType_STRING,
				Description: "The alt text of the featured image.",
			},
			{
				Name:        "link_rel_canonical_url",
				Type:        proto.ColumnType_STRING,
				Description: "Optional override to set the URL to be used in the rel=canonical link tag on the page.",
			},
			{
				Name:        "content_type_category",
				Type:        proto.ColumnType_INT,
				Description: "An ENUM describing the type of this object. Should always be BLOG_POST.",
			},
			{
				Name:        "attached_stylesheets",
				Type:        proto.ColumnType_JSON,
				Description: "List of stylesheets to attach to this blog post. These stylesheets are attached to just this page.",
			},
			{
				Name:        "meta_description",
				Type:        proto.ColumnType_STRING,
				Description: "A description that goes in the <meta> tag on the page.",
			},
			{
				Name:        "head_html",
				Type:        proto.ColumnType_STRING,
				Description: "Custom HTML for embed codes, javascript, etc. that goes in the <head> tag of the page.",
			},
			{
				Name:        "footer_html",
				Type:        proto.ColumnType_STRING,
				Description: "Custom HTML for embed codes, javascript that should be placed before the </body> tag of the page.",
			},
			{
				Name:        "archived_in_dashboard",
				Type:        proto.ColumnType_BOOL,
				Description: "If true, the post will not show up in your dashboard, although the post could still be live.",
			},
			{
				Name:        "public_access_rules_enabled",
				Type:        proto.ColumnType_BOOL,
				Description: "Boolean to determine whether or not to respect public access rules.",
			},
			{
				Name:        "public_access_rules",
				Type:        proto.ColumnType_JSON,
				Description: "Rules for requiring member registration to access private content.",
			},
			{
				Name:        "layout_sections",
				Type:        proto.ColumnType_JSON,
				Description: "Map of layout sections for this Blog Post.",
			},
			{
				Name:        "theme_settings_values",
				Type:        proto.ColumnType_JSON,
				Description: "Map of theme settings values for this Blog Post.",
			},
			{
				Name:        "url",
				Type:        proto.ColumnType_STRING,
				Description: "The generated URL of this blog post.",
			},
			{
				Name:        "password",
				Type:        proto.ColumnType_STRING,
				Description: "Set this to create a password-protected page. Entering the password will be required to view the page.",
			},
			{
				Name:        "current_state",
				Type:        proto.ColumnType_STRING,
				Description: "A generated ENUM describing the current state of this Blog Post. Should always match the 'state' field.",
			},
			{
				Name:        "publish_date",
				Type:        proto.ColumnType_TIMESTAMP,
				Description: "The date and time the blog post is scheduled to be published.",
			},
			{
				Name:        "created",
				Type:        proto.ColumnType_TIMESTAMP,
				Description: "The timestamp when this Blog Post was created.",
			},
			{
				Name:        "updated",
				Type:        proto.ColumnType_TIMESTAMP,
				Description: "The timestamp when this Blog Post was last updated.",
			},
			{
				Name:        "deleted_at",
				Type:        proto.ColumnType_TIMESTAMP,
				Description: "The timestamp when this Blog Post was deleted.",
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

func listBlogPosts(ctx context.Context, d *plugin.QueryData, h *plugin.HydrateData) (interface{}, error) {
	authorizer, err := connect(ctx, d)
	if err != nil {
		plugin.Logger(ctx).Error("hubspot_blog_post.listBlogPosts", "connection_error", err)
		return nil, err
	}
	context := hubspot.WithAuthorizer(context.Background(), authorizer)
	client := blog_posts.NewAPIClient(blog_posts.NewConfiguration())

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
			response, _, err := client.BlogPostsApi.GetPage(context).Limit(maxLimit).Archived(archived).Execute()
			if err != nil {
				plugin.Logger(ctx).Error("hubspot_blog_post.listBlogPosts", "api_error", err)
				return nil, err
			}
			for _, blogPost := range response.Results {
				d.StreamListItem(ctx, blogPost)

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
			response, _, err := client.BlogPostsApi.GetPage(context).Limit(maxLimit).After(after).Archived(archived).Execute()
			if err != nil {
				plugin.Logger(ctx).Error("hubspot_blog_post.listBlogPosts", "api_error", err)
				return nil, err
			}
			for _, blogPost := range response.Results {
				d.StreamListItem(ctx, blogPost)

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

func getBlogPost(ctx context.Context, d *plugin.QueryData, h *plugin.HydrateData) (interface{}, error) {
	id := d.EqualsQualString("id")

	// check if id is empty
	if id == "" {
		return nil, nil
	}

	authorizer, err := connect(ctx, d)
	if err != nil {
		plugin.Logger(ctx).Error("hubspot_blog_post.getBlogPost", "connection_error", err)
		return nil, err
	}
	context := hubspot.WithAuthorizer(context.Background(), authorizer)
	client := blog_posts.NewAPIClient(blog_posts.NewConfiguration())

	blogPost, _, err := client.BlogPostsApi.GetByID(context, id).Execute()
	if err != nil {
		plugin.Logger(ctx).Error("hubspot_blog_post.getBlogPost", "api_error", err)
		return nil, err
	}

	return blogPost, nil
}
