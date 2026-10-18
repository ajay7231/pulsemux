import { ArrowRight, AudioLines, Bot } from "lucide-react";
import { Badge, Empty } from "../../components/ui";
import { editableAgent } from "../../lib/agents";
import type { WorkspacePageProps } from "./types";
type Props = Pick<
  WorkspacePageProps,
  "startModal" | "filtered" | "templates" | "setEditor" | "setAgentTab"
>;
export function AgentsPage({
  filtered,
  templates,
  setEditor,
  setAgentTab,
}: Props) {
  return filtered.length ? (
    <div className="agent-grid">
      {filtered.map((a) => (
        <article className="card agent-card" key={a.id}>
          <div className="agent-card-top">
            <div className="agent-symbol">
              <Bot size={25} />
            </div>
            <Badge value={a.status} />
          </div>
          <h2>{a.name}</h2>
          <p>
            {a.description ||
              templates.find((t) => t.id === a.config.template)?.description}
          </p>
          <div className="agent-meta">
            <span>
              <AudioLines size={14} />
              {a.config.tts_engine === "deepgram"
                ? "Deepgram Aura-2"
                : "Kokoro voice"}
            </span>
            <span>{a.config.department}</span>
          </div>
          <div className="agent-card-bottom">
            <span>Draft revision {a.revision}</span>
            <button
              className="text-button"
              onClick={() => {
                setEditor(editableAgent(a));
                setAgentTab("Identity");
              }}
            >
              Configure
              <ArrowRight size={15} />
            </button>
          </div>
        </article>
      ))}
    </div>
  ) : (
    <section className="card">
      <Empty title="No agents to display">
        Create an agent from a hospital workflow to get started.
      </Empty>
    </section>
  );
}
