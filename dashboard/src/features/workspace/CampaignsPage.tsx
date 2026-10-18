import { Pause, Play } from "lucide-react";
import { Badge, Button, Empty } from "../../components/ui";
import { api } from "../../lib/api";
import { Row } from "../../lib/types";
import type { WorkspacePageProps } from "./types";
type Props = Pick<
  WorkspacePageProps,
  "canEdit" | "busy" | "run" | "filtered" | "refresh" | "setNotice"
>;
export function CampaignsPage({
  canEdit,
  busy,
  run,
  filtered,
  refresh,
  setNotice,
}: Props) {
  return filtered.length ? (
    <div className="campaign-list">
      {filtered.map((c) => (
        <section className="card campaign-card" key={c.id}>
          <div>
            <div className="campaign-heading">
              <h2>{c.name}</h2>
              <Badge value={c.status} />
            </div>
            <p>
              {c.recipients.length} contacts · Up to {c.config.max_attempts}{" "}
              attempts · {c.config.window_start}:00–{c.config.window_end}
              :00 local time
            </p>
            <div className="progress-track">
              <div
                style={{
                  width: `${c.recipients.length ? (c.recipients.filter((r: Row) => ["completed", "failed", "suppressed"].includes(r.status)).length / c.recipients.length) * 100 : 0}%`,
                }}
              />
            </div>
            <small>
              {c.recipients.filter((r: Row) => r.status === "completed").length}{" "}
              completed ·{" "}
              {c.recipients.filter((r: Row) => r.status === "failed").length}{" "}
              failed ·{" "}
              {
                c.recipients.filter((r: Row) => r.status === "suppressed")
                  .length
              }{" "}
              suppressed
            </small>
          </div>
          <div className="actions">
            {canEdit && !["completed", "cancelled"].includes(c.status) && (
              <>
                <Button
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      await api(
                        `/campaigns/${c.id}/${c.status === "running" ? "pause" : "start"}`,
                        "POST",
                      );
                      refresh();
                      setNotice("Campaign updated");
                    })
                  }
                >
                  {c.status === "running" ? (
                    <Pause size={15} />
                  ) : (
                    <Play size={15} />
                  )}{" "}
                  {c.status === "running" ? "Pause" : "Start campaign"}
                </Button>
                <Button
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      await api(`/campaigns/${c.id}/cancel`, "POST");
                      refresh();
                    })
                  }
                >
                  Cancel
                </Button>
              </>
            )}
          </div>
        </section>
      ))}
    </div>
  ) : (
    <section className="card">
      <Empty title="Be there before they need to call">
        Create an appointment reminder or follow-up campaign with local calling
        windows and bounded retries.
      </Empty>
    </section>
  );
}
