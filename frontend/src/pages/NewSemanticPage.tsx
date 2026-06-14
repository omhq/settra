import {
  ArrowLeft,
  ArrowRight,
  Columns3,
  EyeOff,
  Network,
  Sigma,
  Table2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";

const semanticTypes = [
  {
    title: "Table note",
    description:
      "Name a table, describe what it represents, and set its grain.",
    href: "/semantics/table-notes/new",
    icon: Table2,
  },
  {
    title: "Column meaning",
    description: "Clarify a field label, meaning, and semantic type.",
    href: "/semantics/column-meanings/new",
    icon: Columns3,
  },
  {
    title: "Metric",
    description: "Create a reusable SQL metric tied to a semantic table.",
    href: "/semantics/metrics/new",
    icon: Sigma,
  },
  {
    title: "Relationship",
    description: "Connect two semantic columns with an explicit join rule.",
    href: "/semantics/relationships/new",
    icon: Network,
  },
  {
    title: "Hidden field",
    description: "Select a field that should stay out of the semantic layer.",
    href: "/semantics/fields/hide",
    icon: EyeOff,
  },
];

export default function NewSemanticPage() {
  return (
    <div className="space-y-6">
      <div>
        <Button
          to="/semantics"
          variant="ghost"
          className="mb-4 -ml-2 text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" /> Back
        </Button>
        <h1 className="text-2xl font-semibold">Add semantic</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Choose the semantic object to create.
        </p>
      </div>

      <ItemGrid>
        {semanticTypes.map((item) => {
          const Icon = item.icon;

          return (
            <ItemCard
              key={item.href}
              title={
                <span className="flex min-w-0 items-center gap-2">
                  <Icon className="size-4 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 break-words">{item.title}</span>
                </span>
              }
              footer={
                <Button to={item.href} size="sm" variant="primary">
                  Select
                  <ArrowRight className="size-3" />
                </Button>
              }
            >
              <p>{item.description}</p>
            </ItemCard>
          );
        })}
      </ItemGrid>
    </div>
  );
}
