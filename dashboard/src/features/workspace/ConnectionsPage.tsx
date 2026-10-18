import { Badge, Empty } from "../../components/ui";
import { api } from "../../lib/api";
import { date } from "../../lib/format";
import { operationService } from "../../services/platform";
import type { WorkspacePageProps } from "./types";
type Props = Pick<
  WorkspacePageProps,
  | "busy"
  | "isAdmin"
  | "startModal"
  | "run"
  | "filtered"
  | "refresh"
  | "setNotice"
>;
export function ConnectionsPage({
  busy,
  isAdmin,
  startModal,
  run,
  filtered,
  refresh,
  setNotice,
}: Props) {
  return (
    <section className="card">
      {filtered.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Connection</th>
                <th>Provider</th>
                <th>Status</th>
                <th>Last checked</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {filtered.map((c) => (
                <tr key={c.id}>
                  <td>
                    <strong>{c.name}</strong>
                    <small>Credential revision {c.revision} · encrypted</small>
                  </td>
                  <td className="capitalize">{c.provider}</td>
                  <td>
                    <Badge value={!c.active ? "revoked" : c.test_status} />
                  </td>
                  <td>{c.tested_at ? date(c.tested_at) : "Not tested"}</td>
                  <td>
                    <div className="row-actions">
                      {isAdmin && (
                        <>
                          <button
                            onClick={() =>
                              void run(async () => {
                                const result =
                                  await operationService.connectionStatus(c.id);
                                refresh();
                                setNotice(result.message);
                              })
                            }
                            disabled={busy || !c.active}
                          >
                            Test
                          </button>
                          <button
                            onClick={() =>
                              startModal("connection", {
                                id: c.id,
                                name: c.name,
                                provider: c.provider,
                              })
                            }
                          >
                            Rotate
                          </button>
                          <button
                            className="danger-text"
                            onClick={() =>
                              void run(async () => {
                                await api(
                                  `/connections/${c.id}/revoke`,
                                  "POST",
                                );
                                refresh();
                                setNotice("Connection revoked");
                              })
                            }
                            disabled={busy || !c.active}
                          >
                            Revoke
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty title="No connections to display">
          Save Twilio, Deepgram, Groq, or OpenAI credentials. Keys are encrypted
          and never returned to the browser.
        </Empty>
      )}
    </section>
  );
}
