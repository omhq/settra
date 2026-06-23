import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

import { api, type CubeMetaCube, type CubeMetaMember } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ItemCard, ItemGrid } from "@/components/ui/item-grid";
import { StateMessage } from "@/components/ui/state-message";

export default function SemanticCubePage() {
  const navigate = useNavigate();
  const { cubeName } = useParams<{ cubeName: string }>();
  const [cubes, setCubes] = useState<CubeMetaCube[]>([]);
  const [memberQuery, setMemberQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.semantics
      .model()
      .then((summary) => setCubes(summary.cube.meta?.cubes ?? []))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const cube = useMemo(
    () => cubes.find((item) => item.name === cubeName) ?? null,
    [cubeName, cubes],
  );
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

      <MemberSection title="Measures" members={filteredMeasures} />
      <MemberSection title="Dimensions" members={filteredDimensions} />
      {cube.segments.length > 0 && (
        <MemberSection title="Segments" members={filteredSegments} />
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
}: {
  title: string;
  members: CubeMetaMember[];
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
          {members.map((member) => (
            <ItemCard
              key={member.name}
              title={member.title || member.name}
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
              </div>
            </ItemCard>
          ))}
        </ItemGrid>
      )}
    </section>
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
