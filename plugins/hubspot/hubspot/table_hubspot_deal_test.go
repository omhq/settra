package hubspot

import (
	"testing"

	"github.com/clarkmcc/go-hubspot/generated/v3/deals"
)

func TestPrimaryCompanyID(t *testing.T) {
	tests := []struct {
		name         string
		associations map[string]deals.CollectionResponseAssociatedId
		want         string
	}{
		{name: "no associations", want: ""},
		{
			name: "primary company",
			associations: map[string]deals.CollectionResponseAssociatedId{
				"companies": {Results: []deals.AssociatedId{{Id: "123", Type: "deal_to_company"}}},
			},
			want: "123",
		},
		{
			name: "explicit primary company alias",
			associations: map[string]deals.CollectionResponseAssociatedId{
				"companies": {Results: []deals.AssociatedId{{Id: "456", Type: "deal_to_primary_company"}}},
			},
			want: "456",
		},
		{
			name: "unlabeled company is not primary",
			associations: map[string]deals.CollectionResponseAssociatedId{
				"companies": {Results: []deals.AssociatedId{{Id: "789", Type: "deal_to_company_unlabeled"}}},
			},
			want: "",
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			deal := deals.SimplePublicObjectWithAssociations{}
			if test.associations != nil {
				deal.Associations = &test.associations
			}
			if got := primaryCompanyID(deal); got != test.want {
				t.Fatalf("primaryCompanyID() = %q, want %q", got, test.want)
			}
		})
	}
}
