import { Check, ClipboardList } from "lucide-react";
import { Badge, Button, Empty } from "../../components/ui";
import { api } from "../../lib/api";
import { date } from "../../lib/format";
import type { WorkspacePageProps } from "./types";
type Props = Pick<
  WorkspacePageProps,
  "canEdit" | "busy" | "run" | "filtered" | "refresh"
>;
export function TasksPage({ canEdit, busy, run, filtered, refresh }: Props) {
  return (
    <section className="card">
      {filtered.length ? (
        filtered.map((t) => (
          <div className="task-row" key={t.id}>
            <div className="task-symbol">
              <ClipboardList size={20} />
            </div>
            <div>
              <h3>{t.title}</h3>
              <p>{t.details}</p>
              <small>{date(t.created_at)}</small>
            </div>
            <Badge value={t.status} />
            {t.status === "open" && canEdit && (
              <Button
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    await api(`/tasks/${t.id}/resolve`, "POST");
                    refresh();
                  })
                }
              >
                <Check size={15} />
                Resolve
              </Button>
            )}
          </div>
        ))
      ) : (
        <Empty title="Nothing waiting on your team">
          Callback requests, scheduling changes, and provider issues will appear
          here.
        </Empty>
      )}
    </section>
  );
}
