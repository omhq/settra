import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

import {
  api,
  type CubeMetaCube,
  type CubeMetaMember,
  type CubeSourceDefinition,
  type CubeSourceMemberDefinition,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { StateMessage } from "@/components/ui/state-message";

export default function SemanticCubePage() {
  const navigate = useNavigate();
  const { cubeName } = useParams<{ cubeName: string }>();
  const [cubes, setCubes] = useState<CubeMetaCube[]>([]);
  const [sourceDefinitions, setSourceDefinitions] = useState<
    Record<string, CubeSourceDefinition>
  >({});
  const [memberQuery, setMemberQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.semantics
      .model()
      .then((summary) => {
        setCubes(summary.cube.meta?.cubes ?? []);
        setSourceDefinitions(summary.source_definitions?.cubes ?? {});
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const cube = useMemo(
    () => cubes.find((item) => item.name === cubeName) ?? null,
    [cubeName, cubes],
  );
  const cubeSource = cubeName ? sourceDefinitions[cubeName] : undefined;
  const filteredMeasures = useMemo(
    () =>
      (cube?.measures ?? []).filter((member) =>
        matchesSearch(member, memberQuery),
      ),
    [cube?.measures, memberQuery],
  );
  const filteredDimensions = useMemo(
    () =>
      (cube?.dimensions ?? []).filter((member) =>
        matchesSearch(member, memberQuery),
      ),
    [cube?.dimensions, memberQuery],
  );
  const filteredSegments = useMemo(
    () =>
      (cube?.segments ?? []).filter((member) =>
        matchesSearch(member, memberQuery),
      ),
    [cube?.segments, memberQuery],
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
          onClick={() => navigate("/semantics")}
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
        </div>
      </div>

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
      {cube.segments.length > 0 && (
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
  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2">
        <h2 className="text-base font-semibold">{title}</h2>
        <Badge variant="outline">{members.length}</Badge>
      </div>
      {members.length === 0 ? (
        <StateMessage
          state="empty"
          variant="panel"
          title={`No ${title.toLowerCase()}`}
        />
      ) : (
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
                    {member.name}
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
      )}
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
  const definition = definitions?.[localMemberName(member.name)];

  if (!definition) return undefined;

  const parts = [cleanTitle(definition.sql)];
  const filterSql = (definition.filters ?? [])
    .map((filter) => cleanTitle(filter.sql))
    .filter(Boolean);

  if (filterSql.length) {
    parts.push(["filters:", ...filterSql.map((sql) => `- ${sql}`)].join("\n"));
  }

  return parts.filter(Boolean).join("\n\n") || undefined;
}

function localMemberName(name: string): string {
  return name.split(".").pop() ?? name;
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
