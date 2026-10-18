import { Empty } from "../../components/ui";
import { operationService } from "../../services/platform";
import { CallTable } from "../calls/CallTable";
import type { WorkspacePageProps } from "./types";
type Props = Pick<
  WorkspacePageProps,
  "agents" | "run" | "setCall" | "filtered"
>;
export function CallsPage({ agents, run, setCall, filtered }: Props) {
  return (
    <section className="card">
      {filtered.length ? (
        <CallTable
          rows={filtered}
          agents={agents}
          open={(id) =>
            void run(async () => setCall(await operationService.call(id)))
          }
        />
      ) : (
        <Empty title="No calls to display">
          Simulation and telephone calls will appear here with their
          transcripts, sources, and actions.
        </Empty>
      )}
    </section>
  );
}
