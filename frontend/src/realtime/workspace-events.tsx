import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useAuth } from "@/auth/auth-provider";

export type WorkspaceResource =
  | "artifacts"
  | "connections"
  | "google_oauth"
  | "semantic_models"
  | "relationships"
  | "artifact_graphs"
  | "mcp_requests";

export interface WorkspaceChangeEvent {
  id: number;
  organization_id: number;
  resources: (WorkspaceResource | "*")[];
  action: string;
  entity_id: number | null;
  artifact_id: number | null;
  connection_id: number | null;
  entity_key: string | null;
  revision: number | null;
  occurred_at: string;
}

type Listener = (event: WorkspaceChangeEvent) => void;

interface WorkspaceEventsContextValue {
  subscribe: (listener: Listener) => () => void;
}

const WorkspaceEventsContext =
  createContext<WorkspaceEventsContextValue | null>(null);

export const workspaceQueryKeys = {
  root: (organizationId: number) => ["workspace", organizationId] as const,
  resource: (organizationId: number, resource: WorkspaceResource) =>
    ["workspace", organizationId, resource] as const,
};

export function WorkspaceEventsProvider({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const listeners = useRef(new Set<Listener>());
  const organizationId = auth.session?.organization.id ?? null;

  const subscribe = useCallback((listener: Listener) => {
    listeners.current.add(listener);
    return () => listeners.current.delete(listener);
  }, []);

  useEffect(() => {
    if (auth.status !== "authenticated" || organizationId === null) return;

    queryClient.removeQueries({
      queryKey: ["workspace"],
      predicate: (query) => query.queryKey[1] !== organizationId,
    });

    const source = new EventSource("/api/events");

    const notifyListeners = (event: WorkspaceChangeEvent) => {
      for (const listener of listeners.current) listener(event);
    };

    const revalidate = () => {
      void queryClient.invalidateQueries({
        queryKey: workspaceQueryKeys.root(organizationId),
      });
      notifyListeners({
        id: 0,
        organization_id: organizationId,
        resources: ["*"],
        action: "transport_ready",
        entity_id: null,
        artifact_id: null,
        connection_id: null,
        entity_key: null,
        revision: null,
        occurred_at: new Date().toISOString(),
      });
    };

    const changed = (message: MessageEvent<string>) => {
      let event: WorkspaceChangeEvent;
      try {
        event = JSON.parse(message.data) as WorkspaceChangeEvent;
      } catch {
        return;
      }

      if (event.organization_id !== organizationId) return;

      for (const resource of event.resources) {
        if (resource === "*") {
          void queryClient.invalidateQueries({
            queryKey: workspaceQueryKeys.root(organizationId),
          });
        } else {
          void queryClient.invalidateQueries({
            queryKey: workspaceQueryKeys.resource(organizationId, resource),
          });
        }
      }
      notifyListeners(event);
    };

    source.addEventListener("ready", revalidate);
    source.addEventListener("workspace-change", changed as EventListener);

    return () => {
      source.removeEventListener("ready", revalidate);
      source.removeEventListener("workspace-change", changed as EventListener);
      source.close();
    };
  }, [auth.status, organizationId, queryClient]);

  return (
    <WorkspaceEventsContext.Provider value={{ subscribe }}>
      {children}
    </WorkspaceEventsContext.Provider>
  );
}

export function useWorkspaceChange(
  resources: WorkspaceResource[],
  listener: Listener,
) {
  const context = useContext(WorkspaceEventsContext);
  const listenerRef = useRef(listener);
  const resourceKey = resources.join("|");

  useEffect(() => {
    listenerRef.current = listener;
  }, [listener]);

  useEffect(() => {
    if (!context) {
      throw new Error(
        "useWorkspaceChange must be used inside WorkspaceEventsProvider",
      );
    }

    const accepted = new Set(resourceKey.split("|") as WorkspaceResource[]);
    return context.subscribe((event) => {
      if (
        event.resources.includes("*") ||
        event.resources.some(
          (resource) => resource !== "*" && accepted.has(resource),
        )
      ) {
        listenerRef.current(event);
      }
    });
  }, [context, resourceKey]);
}
