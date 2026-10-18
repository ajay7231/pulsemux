import { useQuery } from "@tanstack/react-query";
import type { Resource } from "../contracts/schemas";
import type { Page } from "../lib/types";
import {
  metadataService,
  resourceService,
  type PageOptions,
} from "../services/platform";
export const resourceForPage: Partial<Record<Page, Resource>> = {
  agents: "agents",
  knowledge: "collections",
  connections: "connections",
  numbers: "numbers",
  contacts: "contacts",
  campaigns: "campaigns",
  calls: "calls",
  tasks: "tasks",
  settings: "users",
};
export const workspaceKey = (id: string) => ["workspace", id] as const;
export function useWorkspaceList(
  workspace: string,
  page: Page,
  options: PageOptions,
  admin: boolean,
) {
  const resource = resourceForPage[page];
  return useQuery({
    queryKey: [...workspaceKey(workspace), "resources", resource, options],
    enabled: !!resource && (page !== "settings" || admin),
    queryFn: ({ signal }) => resourceService.list(resource!, options, signal),
  });
}
export function useOptions(
  workspace: string,
  resource: Resource,
  enabled: boolean,
) {
  return useQuery({
    queryKey: [...workspaceKey(workspace), "options", resource],
    enabled,
    queryFn: async ({ signal }) => {
      const first = await resourceService.list(
        resource,
        { pageSize: 100 },
        signal,
      );
      const items = [...first.items];
      for (let page = 2; page <= first.pages; page++) {
        const next = await resourceService.list(
          resource,
          { page, pageSize: 100 },
          signal,
        );
        items.push(...next.items);
      }
      return items;
    },
  });
}
export function useWorkspaceOverview(workspace: string, enabled: boolean) {
  return useQuery({
    queryKey: [...workspaceKey(workspace), "overview"],
    enabled,
    queryFn: ({ signal }) => metadataService.overview(signal),
    refetchInterval: enabled ? 30000 : false,
  });
}
