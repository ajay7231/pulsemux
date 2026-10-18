import { Badge, Empty } from "../../components/ui";
import type { WorkspacePageProps } from "./types";
type Props = Pick<WorkspacePageProps, "canEdit" | "startModal" | "filtered">;
export function ContactsPage({ canEdit, startModal, filtered }: Props) {
  return (
    <section className="card">
      {filtered.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Contact</th>
                <th>Phone</th>
                <th>Calling preference</th>
                <th>Timezone</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {filtered.map((c) => (
                <tr key={c.id}>
                  <td>
                    <strong>{c.name}</strong>
                  </td>
                  <td>{c.phone}</td>
                  <td>
                    <Badge
                      value={
                        c.opted_out
                          ? "opted_out"
                          : c.consent
                            ? "consented"
                            : "no_consent"
                      }
                    />
                  </td>
                  <td>{c.timezone}</td>
                  <td>
                    {canEdit && (
                      <button
                        className="text-button"
                        onClick={() =>
                          startModal("contact", {
                            ...c,
                            variables: JSON.stringify(c.variables, null, 2),
                          })
                        }
                      >
                        Edit
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty title="No contacts to display">
          Add a contact and their calling preferences before scheduling an
          outbound call.
        </Empty>
      )}
    </section>
  );
}
