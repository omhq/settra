import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

import {
  api,
  type CubeMetaCube,
  type CubeMetaMember,
  type CubeSourceDefinition,
  type CubeSourceMemberDefinition,
  type CollectionSemanticModel,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { QueryTester } from "@/components/collections/QueryTester";
import { Input } from "@/components/ui/input";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { StateMessage } from "@/components/ui/state-message";

export default function SemanticCubePage() {
  const navigate = useNavigate();
  const { id, cubeName } = useParams<{ id: string; cubeName: string }>();
  const collectionId = Number(id);
  const [model, setModel] = useState<CollectionSemanticModel | null>(null);
  const [semanticModels, setSemanticModels] = useState<
    CollectionSemanticModel[]
  >([]);
  const [cubes, setCubes] = useState<CubeMetaCube[]>([]);
  const [sourceDefinitions, setSourceDefinitions] = useState<
    Record<string, CubeSourceDefinition>
  >({});
  const [memberQuery, setMemberQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    api.collections
      .models(collectionId)
      .then((catalog) => {
        if (!active) return;
        setSemanticModels(catalog.models);
        setCubes(catalog.models.map((item) => item.meta));
        setModel(catalog.models.find((item) => item.name === cubeName) ?? null);
        setSourceDefinitions(catalog.source_definitions);
      })
      .catch((err) => {
        if (active) setError(err.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [collectionId, cubeName]);

  const cube = useMemo(
    () => cubes.find((item) => item.name === cubeName) ?? null,
    [cubeName, cubes],
  );
  const cubeSource = cubeName ? sourceDefinitions[cubeName] : undefined;
  const filteredMeasures = useMemo(
    () =>
      (cube?.measures ?? [])
        .filter((member) => isUserFacingMember(member, cubeSource?.source_type))
        .filter((member) => matchesSearch(member, memberQuery)),
    [cube?.measures, cubeSource?.source_type, memberQuery],
  );
  const filteredDimensions = useMemo(
    () =>
      (cube?.dimensions ?? [])
        .filter((member) => isUserFacingMember(member, cubeSource?.source_type))
        .filter((member) => matchesSearch(member, memberQuery)),
    [cube?.dimensions, cubeSource?.source_type, memberQuery],
  );
  const filteredSegments = useMemo(
    () =>
      (cube?.segments ?? [])
        .filter((member) => isUserFacingMember(member, cubeSource?.source_type))
        .filter((member) => matchesSearch(member, memberQuery)),
    [cube?.segments, cubeSource?.source_type, memberQuery],
  );

  if (loading) {
    return (
      <StateMessage
        state="loading"
        variant="panel"
        message="Loading semantic block"
      />
    );
  }

  if (error || !cube) {
    return (
      <StateMessage
        state="error"
        variant="panel"
        message={error ?? "Semantic block not found"}
      />
    );
  }

  return (
    <div className="max-w-6xl space-y-6">
      <div>
        <Button
          type="button"
          variant="ghost"
          onClick={() =>
            navigate(
              model
                ? `/data/apps/${collectionId}/model?path=${encodeURIComponent(model.path)}`
                : `/data/apps/${collectionId}?section=models`,
            )
          }
          className="mb-4 -ml-2 text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" /> Back
        </Button>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="break-words text-2xl font-semibold">
              {cube.title || cube.name}
            </h1>
            <p className="mt-1 break-words text-sm text-muted-foreground">
              {cube.name}
            </p>
          </div>
          <QueryTester
            collectionId={collectionId}
            models={semanticModels}
            initialCubeName={cube.name}
          />
        </div>
      </div>

      {model && !model.in_scope && (
        <StateMessage
          state="warning"
          variant="banner"
          message="This model is retained in its artifact, but requires unavailable sources or dependencies. Restore them or update the model before querying it."
        />
      )}
      {model && !model.compile.compiled && (
        <StateMessage
          state="warning"
          variant="banner"
          message={
            model.compile.error ||
            "Cube has not confirmed this model's stored revision. The stored definition is still available."
          }
        />
      )}

      <section className="space-y-3">
        <h2 className="text-base font-semibold">Description</h2>
        <p className="mt-2 whitespace-pre-wrap text-sm leading-6">
          {cube.description || "No description available."}
        </p>
      </section>

      <Input
        type="search"
        value={memberQuery}
        onChange={(event) => setMemberQuery(event.target.value)}
        placeholder="Filter measures, dimensions, and segments"
        aria-label="Filter semantic block members"
        className="max-w-sm"
      />

      <MemberSection
        title="Measures"
        members={filteredMeasures}
        definitions={cubeSource?.measures}
      />
      <MemberSection
        title="Dimensions"
        members={filteredDimensions}
        definitions={cubeSource?.dimensions}
      />
      {cube.segments.some((member) =>
        isUserFacingMember(member, cubeSource?.source_type),
      ) && (
        <MemberSection
          title="Segments"
          members={filteredSegments}
          definitions={cubeSource?.segments}
        />
      )}
      {cube.joins && cube.joins.length > 0 && <JoinSection cube={cube} />}
    </div>
  );
}

function matchesSearch(value: unknown, query: string): boolean {
  const normalizedQuery = query.trim().toLowerCase();

  if (!normalizedQuery) return true;

  return searchableText(value).includes(normalizedQuery);
}

function searchableText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value.toLowerCase();
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value).toLowerCase();
  }
  if (Array.isArray(value)) return value.map(searchableText).join(" ");
  if (typeof value === "object") {
    return Object.values(value as Record<string, unknown>)
      .map(searchableText)
      .join(" ");
  }

  return "";
}

function MemberSection({
  title,
  members,
  definitions,
}: {
  title: string;
  members: CubeMetaMember[];
  definitions?: Record<string, CubeSourceMemberDefinition>;
}) {
  if (members.length === 0) return null;

  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2">
        <h2 className="text-base font-semibold">{title}</h2>
        <Badge variant="outline">{members.length}</Badge>
      </div>
      <ItemGrid className="lg:grid-cols-2 xl:grid-cols-3">
        {members.map((member) => {
          const snippet = memberDefinitionSnippet(member, definitions);

          return (
            <ItemCard
              key={member.name}
              title={memberDisplayTitle(member)}
              pills={
                <>
                  {member.type && (
                    <Badge variant="secondary">{member.type}</Badge>
                  )}
                  {member.aggType && (
                    <Badge variant="outline">{member.aggType}</Badge>
                  )}
                </>
              }
            >
              <div className="space-y-2">
                <p className="break-words font-mono text-xs text-foreground">
                  {localMemberName(member.name)}
                </p>
                {member.description && (
                  <p className="whitespace-pre-wrap">{member.description}</p>
                )}
                {snippet && (
                  <pre className="max-h-24 overflow-auto whitespace-pre-wrap rounded-md border bg-muted/50 p-2 font-mono text-[11px] leading-5 text-foreground">
                    {snippet}
                  </pre>
                )}
              </div>
            </ItemCard>
          );
        })}
      </ItemGrid>
    </section>
  );
}

function memberDisplayTitle(member: CubeMetaMember): string {
  return (
    cleanTitle(member.shortTitle) ??
    cleanTitle(member.title) ??
    humanizeMemberName(member.name)
  );
}

function cleanTitle(value: string | null | undefined): string | undefined {
  const trimmed = value?.trim();

  return trimmed || undefined;
}

function humanizeMemberName(name: string): string {
  const localName = name.split(".").pop() ?? name;

  return localName
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase())
    .replace(/\bId\b/g, "ID")
    .replace(/\bUsd\b/g, "USD");
}

function memberDefinitionSnippet(
  member: CubeMetaMember,
  definitions: Record<string, CubeSourceMemberDefinition> | undefined,
): string | undefined {
  const memberName = localMemberName(member.name);
  const definition = definitions?.[memberName];

  if (!definition) return undefined;

  const sql = cleanTitle(definition.sql);
  const parts =
    sql && !isDirectColumnMapping(sql, memberName) ? [`${sql}`] : [];
  const filterSql = (definition.filters ?? [])
    .map((filter) => cleanTitle(filter.sql))
    .filter(Boolean);

  if (filterSql.length) {
    parts.push(
      filterSql
        .map((sql, index) => `${index === 0 ? "where" : "and"} ${sql}`)
        .join("\n"),
    );
  }

  return parts.filter(Boolean).join("\n\n") || undefined;
}

function isDirectColumnMapping(sql: string, memberName: string): boolean {
  const expression = sql.trim().replace(/^\{CUBE\}\./, "");

  return expression === memberName || expression === `"${memberName}"`;
}

function localMemberName(name: string): string {
  return name.split(".").pop() ?? name;
}

function isUserFacingMember(
  member: CubeMetaMember,
  sourceType?: CubeSourceDefinition["source_type"],
): boolean {
  if (member.public === false || member.isVisible === false) return false;

  const localName = localMemberName(member.name).toLowerCase();
  const settraMeta = member.meta?.settra;
  const explicitlyInternal =
    typeof settraMeta === "object" &&
    settraMeta !== null &&
    "internal" in settraMeta &&
    settraMeta.internal === true;
  return (
    !explicitlyInternal &&
    (sourceType === "generated_connection" || localName !== "source_pipe") &&
    !localName.startsWith("_dlt_")
  );
}

function JoinSection({ cube }: { cube: CubeMetaCube }) {
  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2">
        <h2 className="text-base font-semibold">Joins</h2>
        <Badge variant="outline">{cube.joins?.length ?? 0}</Badge>
      </div>
      <ItemGrid className="lg:grid-cols-2 xl:grid-cols-3">
        {cube.joins?.map((join) => (
          <ItemCard
            key={`${join.name}-${join.relationship}`}
            title={join.name}
            pills={<Badge variant="secondary">{join.relationship}</Badge>}
          />
        ))}
      </ItemGrid>
    </section>
  );
}
