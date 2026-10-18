import { z } from "zod";
import type { components } from "../contracts/generated";
import {
  agentSchema,
  callSchema,
  connectionSchema,
  modelCatalogSchema,
  overviewSchema,
  parsePage,
  sessionSchema,
  templateSchema,
  type Resource,
} from "../contracts/schemas";
import { api, ApiError } from "../lib/api";
export type AgentInput = components["schemas"]["AgentInput"];
export type ConnectionInput = components["schemas"]["ConnectionInput"];
export type PageOptions = {
  page?: number;
  pageSize?: number;
  search?: string;
  sort?: "created_at" | "name" | "status";
  direction?: "asc" | "desc";
};
export function validate<T>(schema: z.ZodType<T>, data: unknown): T {
  const result = schema.safeParse(data);
  if (!result.success)
    throw new ApiError(
      "The server returned data in an unsupported format. Reload or contact your administrator.",
      502,
      "invalid_response",
    );
  return result.data;
}
export const sessionService = {
  me: async (signal?: AbortSignal) =>
    validate(
      sessionSchema,
      await api<unknown>("/me", "GET", undefined, { signal, auth: "optional" }),
    ),
  bootstrap: async (signal?: AbortSignal) =>
    validate(
      z.object({
        setup_required: z.boolean(),
        setup_token_required: z.boolean(),
      }),
      await api<unknown>("/bootstrap", "GET", undefined, {
        signal,
        auth: "optional",
      }),
    ),
  logout: () =>
    api<{ ok: boolean }>("/logout", "POST", undefined, { auth: "optional" }),
};
export const resourceService = {
  async list<K extends Resource>(
    resource: K,
    options: PageOptions = {},
    signal?: AbortSignal,
  ) {
    const params = new URLSearchParams({
      page: String(options.page ?? 1),
      page_size: String(options.pageSize ?? 25),
      q: options.search ?? "",
      sort: options.sort ?? "created_at",
      direction: options.direction ?? "desc",
    });
    const data = await api<unknown>(
      `/resources/${resource}?${params}`,
      "GET",
      undefined,
      { signal },
    );
    try {
      return parsePage(resource, data);
    } catch {
      throw new ApiError(
        "The server returned an invalid resource list. Please reload.",
        502,
        "invalid_response",
      );
    }
  },
};
export const agentService = {
  publish: async (id: string) =>
    validate(
      agentSchema,
      await api<unknown>(`/agents/${encodeURIComponent(id)}/publish`, "POST"),
    ),
  get: async (id: string, signal?: AbortSignal) =>
    validate(
      agentSchema,
      await api<unknown>(
        `/agents/${encodeURIComponent(id)}`,
        "GET",
        undefined,
        { signal },
      ),
    ),
  save: async (data: AgentInput, id?: string) =>
    validate(
      agentSchema,
      await api<unknown>(
        id ? `/agents/${encodeURIComponent(id)}` : "/agents",
        id ? "PUT" : "POST",
        data,
      ),
    ),
};
export const connectionService = {
  save: async (data: ConnectionInput, id?: string) =>
    validate(
      connectionSchema,
      await api<unknown>(
        id ? `/connections/${encodeURIComponent(id)}` : "/connections",
        id ? "PUT" : "POST",
        data,
      ),
    ),
};
export const userService = {
  disable: (id: string) =>
    api(`/users/${encodeURIComponent(id)}/disable`, "POST"),
  revokeSessions: (id: string) =>
    api<{ ok: boolean }>(
      `/users/${encodeURIComponent(id)}/revoke-sessions`,
      "POST",
    ),
};

export const metadataService = {
  knowledgeConfig: async () =>
    validate(
      z.object({ hybrid_enabled: z.boolean() }),
      await api<unknown>("/knowledge/config"),
    ),
  templates: async (signal?: AbortSignal) =>
    validate(
      z.array(templateSchema),
      await api<unknown>("/templates", "GET", undefined, { signal }),
    ),
  overview: async (signal?: AbortSignal) =>
    validate(
      overviewSchema,
      await api<unknown>("/overview", "GET", undefined, { signal }),
    ),
  models: async (connection: string, signal?: AbortSignal) =>
    validate(
      modelCatalogSchema,
      await api<unknown>(
        `/connections/${encodeURIComponent(connection)}/models`,
        "GET",
        undefined,
        { signal },
      ),
    ),
};

const documentSchema = z.object({
  id: z.string(),
  workspace_id: z.string(),
  created_at: z.number(),
  collection_id: z.string(),
  title: z.string(),
  content: z.string(),
  status: z.string(),
  ingestion_status: z.string().default("legacy"),
  ingestion_error: z.string().nullable().default(null),
  reviewed_by: z.string().nullable(),
  reviewed_at: z.number().nullable(),
  expires_at: z.number().nullable(),
});
const contactInputSchema = z.object({
  name: z.string(),
  phone: z.string(),
  consent: z.boolean(),
  opted_out: z.boolean(),
  timezone: z.string(),
  variables: z.record(z.string(), z.json()),
});
export const operationService = {
  connectionStatus: async (id: string) =>
    validate(
      z.object({ status: z.string(), message: z.string() }),
      await api<unknown>(`/connections/${encodeURIComponent(id)}/test`, "POST"),
    ),
  outbound: async (input: components["schemas"]["OutboundInput"]) =>
    validate(
      z.object({ id: z.string(), error: z.string().nullable() }),
      await api<unknown>("/calls/outbound", "POST", input),
    ),
  importPreview: async (file: FormData) =>
    validate(
      z.object({
        contacts: z.array(contactInputSchema),
        errors: z.array(z.object({ line: z.number(), message: z.string() })),
      }),
      await api<unknown>("/contacts/import-preview", "POST", file),
    ),
  importContacts: async (contacts: components["schemas"]["ContactInput"][]) =>
    validate(
      z.object({ imported: z.number(), duplicates: z.number() }),
      await api<unknown>("/contacts/import", "POST", contacts),
    ),
  indexDocument: async (id: string) =>
    validate(
      z.object({ indexed_chunks: z.number(), status: z.string().optional() }),
      await api<unknown>(`/documents/${encodeURIComponent(id)}/index`, "POST"),
    ),
  documents: async (id: string) =>
    validate(
      z.array(documentSchema),
      await api<unknown>(`/collections/${encodeURIComponent(id)}/documents`),
    ),
  call: async (id: string) =>
    validate(
      callSchema.extend({
        events: z.array(
          z.object({
            id: z.string(),
            created_at: z.number(),
            kind: z.string(),
            payload: z.record(z.string(), z.json()),
          }),
        ),
      }),
      await api<unknown>(`/calls/${encodeURIComponent(id)}`),
    ),
};
