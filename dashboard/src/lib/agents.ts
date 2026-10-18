import type { Row } from "./types";

/** The editable fields that define whether a saved draft has changed. */
export function agentFingerprint(agent: Row): string {
  return JSON.stringify({
    name: agent.name,
    description: agent.description,
    config: agent.config,
  });
}

export function editableAgent(agent: Row): Row {
  return { ...agent, _savedFingerprint: agentFingerprint(agent) };
}
