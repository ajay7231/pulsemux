import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSession } from "../../app/SessionProvider";
import { workspaceKey } from "../../app/useWorkspaceQueries";
import { Button } from "../../components/ui";
import { date } from "../../lib/format";
import { resourceService } from "../../services/platform";
export function AuditLog() {
  const { session } = useSession();
  const [page, setPage] = useState(1),
    [search, setSearch] = useState("");
  const query = useQuery({
    queryKey: [
      ...workspaceKey(session!.workspace.id),
      "resources",
      "audit",
      { page, search },
    ],
    queryFn: ({ signal }) =>
      resourceService.list("audit", { page, search }, signal),
  });
  return (
    <div className="modal-content">
      <label className="field">
        <span>Search audit actions</span>
        <input
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setPage(1);
          }}
        />
      </label>
      {query.isPending ? (
        <p role="status">Loading audit history…</p>
      ) : query.error ? (
        <div role="alert">
          <p>{query.error.message}</p>
          <Button onClick={() => void query.refetch()}>Retry</Button>
        </div>
      ) : (
        <>
          <div className="audit-list">
            {query.data.items.length ? (
              query.data.items.map((item) => (
                <div key={item.id}>
                  <strong>{item.action}</strong>
                  <span>{date(item.created_at)}</span>
                </div>
              ))
            ) : (
              <p>No matching audit events.</p>
            )}
          </div>
          <nav className="pagination" aria-label="Audit pages">
            <Button disabled={page <= 1} onClick={() => setPage(page - 1)}>
              Previous
            </Button>
            <span>
              Page {page} of {Math.max(1, query.data.pages)} ·{" "}
              {query.data.total} events
            </span>
            <Button
              disabled={page >= query.data.pages}
              onClick={() => setPage(page + 1)}
            >
              Next
            </Button>
          </nav>
        </>
      )}
    </div>
  );
}
