import { z } from "zod";
const base = {
  id: z.string(),
  workspace_id: z.string(),
  created_at: z.number(),
};
export const userSchema = z.object({
  ...base,
  name: z.string(),
  email: z.string(),
  role: z.enum(["admin", "operator", "viewer"]),
  active: z.boolean(),
});
export const workspaceSchema = z.object({
  id: z.string(),
  name: z.string(),
  timezone: z.string(),
  retention_days: z.number(),
  created_at: z.number(),
});
export const sessionSchema = z.object({
  user: userSchema,
  workspace: workspaceSchema,
});
export const connectionSchema = z.object({
  ...base,
  name: z.string(),
  provider: z.enum(["deepgram", "groq", "openai", "twilio"]),
  revision: z.number(),
  active: z.boolean(),
  test_status: z.string(),
  tested_at: z.number().nullable(),
});
export const configSchema = z.object({
  template: z.string(),
  department: z.string(),
  language: z.string(),
  greeting: z.string(),
  instructions: z.string(),
  tone: z.string(),
  stt_engine: z.enum(["deepgram", "groq"]),
  stt_connection_id: z.string().nullable(),
  llm_connection_id: z.string().nullable(),
  llm_model: z.string(),
  tts_engine: z.enum(["kokoro", "deepgram"]),
  tts_connection_id: z.string().nullable(),
  voice_id: z.string(),
  collection_ids: z.array(z.string()),
  tools: z.array(z.string()),
  transfer_number: z.string(),
  emergency_instructions: z.string(),
  max_duration_seconds: z.number(),
  silence_timeout_seconds: z.number(),
  end_pause_ms: z.number(),
});
export const agentSchema = z.object({
  ...base,
  name: z.string(),
  description: z.string(),
  config: configSchema,
  revision: z.number(),
  status: z.string(),
  updated_at: z.number(),
  published_version_id: z.string().nullable(),
  tested_revision: z.number().nullable(),
  tested_knowledge_hash: z.string().nullable(),
});
export const contactSchema = z.object({
  ...base,
  name: z.string(),
  phone: z.string(),
  consent: z.boolean(),
  opted_out: z.boolean(),
  timezone: z.string(),
  variables: z.record(z.string(), z.json()),
});
export const collectionSchema = z.object({
  ...base,
  name: z.string(),
  description: z.string(),
  embedding_connection_id: z.string().nullable(),
});
export const numberSchema = z.object({
  ...base,
  number: z.string(),
  connection_id: z.string(),
  agent_id: z.string(),
  label: z.string(),
});
export const callSchema = z.object({
  ...base,
  agent_id: z.string(),
  agent_name: z.string().nullable().optional(),
  direction: z.string(),
  status: z.string(),
  to_number: z.string().nullable(),
  from_number: z.string().nullable(),
  outcome: z.string().nullable(),
  error: z.string().nullable(),
  ended_at: z.number().nullable(),
});
export const taskSchema = z.object({
  ...base,
  call_id: z.string().nullable(),
  title: z.string(),
  details: z.string(),
  status: z.string(),
});
export const campaignSchema = z.object({
  ...base,
  name: z.string(),
  agent_version_id: z.string(),
  phone_number_id: z.string(),
  status: z.string(),
  config: z.record(z.string(), z.json()),
  recipient_count: z.number(),
  completed_count: z.number(),
  failed_count: z.number(),
  suppressed_count: z.number(),
});
export const auditSchema = z.object({
  ...base,
  actor_id: z.string().nullable(),
  action: z.string(),
  target_id: z.string().nullable(),
  detail: z.record(z.string(), z.json()),
});
export const resourceSchemas = {
  agents: agentSchema,
  connections: connectionSchema,
  contacts: contactSchema,
  collections: collectionSchema,
  numbers: numberSchema,
  calls: callSchema,
  tasks: taskSchema,
  campaigns: campaignSchema,
  users: userSchema,
  audit: auditSchema,
};
export type Resource = keyof typeof resourceSchemas;
export type Session = z.infer<typeof sessionSchema>;
export type Agent = z.infer<typeof agentSchema>;
export type AgentConfig = z.infer<typeof configSchema>;
export type ConfigUpdate = <K extends keyof AgentConfig>(
  key: K,
  value: AgentConfig[K],
) => void;
export type User = z.infer<typeof userSchema>;
export type PageResult<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
};
export function parsePage<K extends Resource>(
  resource: K,
  input: unknown,
): PageResult<z.infer<(typeof resourceSchemas)[K]>> {
  return z
    .object({
      items: z.array(resourceSchemas[resource]),
      total: z.number(),
      page: z.number(),
      page_size: z.number(),
      pages: z.number(),
    })
    .parse(input) as PageResult<z.infer<(typeof resourceSchemas)[K]>>;
}

export const templateSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string(),
  greeting: z.string(),
  instructions: z.string(),
});
export const modelCatalogSchema = z.object({
  provider: z.enum(["groq", "openai"]),
  models: z.array(z.object({ id: z.string(), name: z.string() })),
});
export const overviewSchema = z.object({
  agents: z.number(),
  calls: z.number(),
  campaigns: z.number(),
  contacts: z.number(),
  active_calls: z.number(),
  open_tasks: z.number(),
  connections: z.number(),
  collections: z.number(),
  numbers: z.number(),
  recent_calls: z.array(callSchema),
  agent_choices: z.array(z.object({ id: z.string(), name: z.string() })),
  recent_activity: z.array(auditSchema),
});
