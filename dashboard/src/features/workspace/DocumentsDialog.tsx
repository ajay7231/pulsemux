import { FileText, Plus, Upload } from "lucide-react";
import { Badge, Button, Empty } from "../../components/ui";
import { api } from "../../lib/api";
import { date } from "../../lib/format";
import { operationService } from "../../services/platform";

import type { WorkspaceDialogContentProps } from "./dialogTypes";
export function DocumentsDialog({
  canEdit,
  setDraft,
  setModal,
  run,
  selected,
  setDocuments,
  setNotice,
  documents,
  isAdmin,
  busy,
  refresh,
}: Pick<
  WorkspaceDialogContentProps,
  | "canEdit"
  | "setDraft"
  | "setModal"
  | "run"
  | "selected"
  | "setDocuments"
  | "setNotice"
  | "documents"
  | "isAdmin"
  | "busy"
  | "refresh"
>) {
  return (
    <div className="modal-content">
      <div className="document-actions">
        {canEdit && (
          <>
            <Button
              onClick={() => {
                setDraft({});
                setModal("document");
              }}
            >
              <Plus size={16} />
              Add text
            </Button>
            <label className="button">
              <Upload size={16} />
              Upload file
              <input
                type="file"
                accept=".pdf,.txt,.md,.csv"
                hidden
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file)
                    void run(async () => {
                      const form = new FormData();
                      form.append("file", file);
                      await api(
                        `/collections/${selected!.id}/upload`,
                        "POST",
                        form,
                      );
                      setDocuments(
                        await operationService.documents(selected!.id),
                      );
                      setNotice("Document uploaded as draft");
                    });
                }}
              />
            </label>
          </>
        )}
        <span className="muted">PDF, TXT, MD, CSV · up to 5 MB</span>
      </div>
      {documents.length ? (
        documents.map((d) => (
          <div className="document-row" key={d.id}>
            <FileText size={22} />
            <div>
              <strong>{d.title}</strong>
              <p>{d.content.slice(0, 160)}…</p>
              <small>
                {d.content.length.toLocaleString()} characters ·{" "}
                {date(d.created_at)}
              </small>
            </div>
            <Badge value={d.status} />
            {isAdmin && (
              <div className="row-actions">
                {canEdit && selected?.embedding_connection_id && (
                  <button
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        const result = await operationService.indexDocument(
                          d.id,
                        );
                        setNotice(
                          `${result.indexed_chunks} chunks indexed for semantic search`,
                        );
                      })
                    }
                  >
                    Index semantic
                  </button>
                )}
                {d.status === "draft" && (
                  <button
                    onClick={() =>
                      void run(async () => {
                        await api(`/documents/${d.id}/approve`, "POST");
                        setDocuments(
                          await operationService.documents(selected!.id),
                        );
                      })
                    }
                  >
                    Approve
                  </button>
                )}
                {d.status !== "archived" && (
                  <button
                    onClick={() =>
                      void run(async () => {
                        await api(`/documents/${d.id}/archive`, "POST");
                        setDocuments(
                          await operationService.documents(selected!.id),
                        );
                        refresh();
                      })
                    }
                  >
                    Archive
                  </button>
                )}
              </div>
            )}
          </div>
        ))
      ) : (
        <Empty title="This collection is ready for its first document">
          Add reference text or upload a file. Documents require approval before
          agents can use them.
        </Empty>
      )}
    </div>
  );
}
