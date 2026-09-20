import type { AppDependencyImpact, WorkspaceDependencyImpact } from "@/lib/api";

export function DependencyImpactSummary({
  impact,
}: {
  impact: AppDependencyImpact;
}) {
  if (!impact.has_impact) {
    return (
      <p className="text-sm text-muted-foreground">
        No semantic models, relationships, or graph outputs depend on this item.
      </p>
    );
  }

  return (
    <div className="space-y-3 text-sm">
      <p>
        This affects {impact.summary.model_count} model
        {impact.summary.model_count === 1 ? "" : "s"},{" "}
        {impact.summary.relationship_count} relationship
        {impact.summary.relationship_count === 1 ? "" : "s"}, and{" "}
        {impact.summary.calculation_output_count} graph output
        {impact.summary.calculation_output_count === 1 ? "" : "s"}.
      </p>
      {impact.affected.models.length > 0 && (
        <ImpactList
          title="Models"
          items={impact.affected.models.map((model) =>
            model.direct
              ? model.title + " (" + model.kind + ", direct)"
              : model.title + " (" + model.kind + ")",
          )}
        />
      )}
      {impact.affected.relationships.length > 0 && (
        <ImpactList
          title="Relationships"
          items={impact.affected.relationships.map(
            (relationship) =>
              relationship.source_model + " -> " + relationship.target_model,
          )}
        />
      )}
      {impact.affected.calculations.length > 0 && (
        <ImpactList
          title="Graph"
          items={impact.affected.calculations.map((calculation) =>
            calculation.outputs.length
              ? calculation.name + ": " + calculation.outputs.join(", ")
              : calculation.name + ": affected draft nodes",
          )}
        />
      )}
    </div>
  );
}

export function WorkspaceDependencyImpactSummary({
  impact,
}: {
  impact: WorkspaceDependencyImpact;
}) {
  if (!impact.has_impact) {
    return (
      <p className="text-sm text-muted-foreground">
        No App dependencies are currently affected.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{impact.message}</p>
      {impact.apps.map((appImpact) => (
        <div key={appImpact.app.id} className="space-y-2 rounded-md border p-3">
          <p className="font-medium">{appImpact.app.name}</p>
          <DependencyImpactSummary impact={appImpact} />
        </div>
      ))}
    </div>
  );
}

function ImpactList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <p className="font-medium">{title}</p>
      <ul className="mt-1 list-disc space-y-1 pl-5 text-muted-foreground">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
