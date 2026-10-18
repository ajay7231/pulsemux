import { ArrowRight, BookOpen } from "lucide-react";
import { Empty } from "../../components/ui";
import { operationService } from "../../services/platform";
import type { WorkspacePageProps } from "./types";
type Props = Pick<
  WorkspacePageProps,
  "run" | "filtered" | "setSelected" | "setDocuments" | "setModal"
>;
export function KnowledgePage({
  run,
  filtered,
  setSelected,
  setDocuments,
  setModal,
}: Props) {
  return filtered.length ? (
    <div className="agent-grid">
      {filtered.map((c) => (
        <article className="card collection-card" key={c.id}>
          <div className="agent-symbol">
            <BookOpen size={25} />
          </div>
          <h2>{c.name}</h2>
          <p>
            {c.description || "Approved reference information for your agents."}
          </p>
          <button
            className="text-button"
            onClick={() =>
              void run(async () => {
                setSelected(c);
                setDocuments(await operationService.documents(c.id));
                setModal("documents");
              })
            }
          >
            Manage documents
            <ArrowRight size={16} />
          </button>
        </article>
      ))}
    </div>
  ) : (
    <section className="card">
      <Empty title="Give your agents a source of truth">
        Create a collection for policies, FAQs, or approved patient
        instructions.
      </Empty>
    </section>
  );
}
