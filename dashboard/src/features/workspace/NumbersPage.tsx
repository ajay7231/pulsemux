import { ArrowRight } from "lucide-react";
import { Empty } from "../../components/ui";
import type { WorkspacePageProps } from "./types";
type Props = Pick<
  WorkspacePageProps,
  "agents" | "filtered" | "setSelected" | "setModal"
>;
export function NumbersPage({
  agents,
  filtered,
  setSelected,
  setModal,
}: Props) {
  return (
    <section className="card">
      {filtered.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Phone number</th>
                <th>Inbound agent</th>
                <th>Setup</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((n) => (
                <tr key={n.id}>
                  <td>
                    <strong>{n.number}</strong>
                    <small>{n.label}</small>
                  </td>
                  <td>{agents.find((a) => a.id === n.agent_id)?.name}</td>
                  <td>
                    <button
                      className="text-button"
                      onClick={() => {
                        setSelected(n);
                        setModal("number-help");
                      }}
                    >
                      Webhook instructions
                      <ArrowRight size={15} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty title="No phone numbers to display">
          Assign a Twilio number you own, then route its incoming calls to a
          published agent.
        </Empty>
      )}
    </section>
  );
}
