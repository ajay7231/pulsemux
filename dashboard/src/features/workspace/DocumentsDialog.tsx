import { useEffect, useState } from "react";
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
  const [refreshError, setRefreshError] = useState("");
  const pending = documents.some((d) =>
    ["queued", "processing"].includes(d.ingestion_status),
  );
  useEffect(() => {
    if (!pending || !selected?.id) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const refreshStatus = async () => {
      try {
        const next = await operationService.documents(selected.id);
        if (!cancelled) {
          setDocuments(next);
          setRefreshError("");
        }
      } catch {
        if (!cancelled)
          setRefreshError(
            "Could not refresh ingestion status. Reopen this collection to retry.",
          );
      }
      if (!cancelled) timer = setTimeout(() => void refreshStatus(), 2000);
    };
    timer = setTimeout(() => void refreshStatus(), 2000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [pending, selected?.id, setDocuments]);
  return (
    <div className="modal-content">
      {refreshError && (
        <p className="field-error" role="alert">
          {refreshError}
        </p>
      )}
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
              Upload documents
              <input
                type="file"
                multiple
                disabled={busy}
                accept=".pdf,.txt,.md,.csv"
                hidden
                onChange={(e) => {
                  const files = Array.from(e.target.files || []);
                  e.target.value = "";
                  if (files.length)
                    void run(async () => {
                      if (files.length > 10)
                        throw new Error(
                          "Choose up to 10 documents per upload.",
                        );
                      const failures: string[] = [];
                      let saved = 0;
                      for (const file of files) {
                        try {
                          if (file.size > 5 * 1024 * 1024)
                            throw new Error("File exceeds 5 MB");
                          const form = new FormData();
                          form.append("file", file);
                          await api(
                            `/collections/${selected!.id}/upload`,
                            "POST",
                            form,
                          );
                          saved++;
                        } catch {
                          failures.push(file.name);
                        }
                      }
                      setDocuments(
                        await operationService.documents(selected!.id),
                      );
                      setNotice(
                        `${saved} document(s) uploaded as drafts. Processing and approval status appear below.`,
                      );
                      if (failures.length)
                        throw new Error(
                          `Could not upload: ${failures.join(", ")}. Successfully uploaded files were retained.`,
                        );
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
            <div>
              <Badge value={d.status} />
              {d.ingestion_status !== "legacy" && (
                <Badge value={d.ingestion_status} />
              )}
              {d.ingestion_error && (
                <p role="alert" className="field-error">
                  {d.ingestion_error}
                </p>
              )}
            </div>
            {isAdmin && (
              <div className="row-actions">
                {canEdit &&
                  (d.ingestion_status === "failed" ||
                    d.ingestion_status === "legacy") && (
                    <button
                      disabled={busy}
                      onClick={() =>
                        void run(async () => {
                          const result = await operationService.indexDocument(
                            d.id,
                          );
                          setNotice(
                            result.status
                              ? "Document queued for clinical ingestion. Approve it again once processing completes."
                              : `${result.indexed_chunks} chunks indexed for semantic search`,
                          );
                          setDocuments(
                            await operationService.documents(selected!.id),
                          );
                        })
                      }
                    >
                      {d.ingestion_status === "failed"
                        ? "Retry ingestion"
                        : "Index knowledge"}
                    </button>
                  )}
                {d.status === "draft" &&
                  ["ready", "legacy"].includes(d.ingestion_status) && (
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
