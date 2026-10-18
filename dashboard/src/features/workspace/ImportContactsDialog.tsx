import { Upload } from "lucide-react";
import { Button } from "../../components/ui";
import { Row } from "../../lib/types";
import { operationService } from "../../services/platform";

import type { WorkspaceDialogContentProps } from "./dialogTypes";
export function ImportContactsDialog({
  draft,
  setDraft,
  run,
  saveDone,
  setModal,
  busy,
}: Pick<
  WorkspaceDialogContentProps,
  "draft" | "setDraft" | "run" | "saveDone" | "setModal" | "busy"
>) {
  return (
    <div className="modal-content">
      <p>
        CSV headers: <strong>name, phone, consent, timezone</strong>. Additional
        columns become agent variables. Consent must explicitly be true, yes, or
        1; missing consent defaults to false. Existing phone numbers are
        skipped.
      </p>
      <label className="button upload-button">
        <Upload size={16} />
        Choose CSV
        <input
          type="file"
          accept=".csv"
          className="upload-input"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file)
              void run(async () => {
                const form = new FormData();
                form.append("file", file);
                const result = await operationService.importPreview(form);
                setDraft(result);
              });
          }}
        />
      </label>
      {draft.contacts && (
        <>
          <p style={{ marginTop: 20 }}>
            {draft.contacts.length} valid contacts · {draft.errors.length}{" "}
            invalid rows
          </p>
          {draft.errors.map((e: Row) => (
            <p key={e.line} className="muted">
              Line {e.line}: {e.message}
            </p>
          ))}
          <div className="audience-list">
            {draft.contacts.slice(0, 20).map((c: Row, i: number) => (
              <div className="checkbox-line" key={i}>
                {c.name}
                <small>
                  {c.phone} · {c.consent ? "consented" : "no consent"}
                </small>
              </div>
            ))}
          </div>
          <div className="modal-footer">
            <Button onClick={() => setModal("")}>Cancel</Button>
            <Button
              kind="primary"
              disabled={
                busy || !draft.contacts.length || draft.errors.length > 0
              }
              onClick={() =>
                void run(async () => {
                  const result = await operationService.importContacts(
                    draft.contacts,
                  );
                  saveDone(
                    `${result.imported} contacts imported; ${result.duplicates} existing numbers skipped`,
                  );
                })
              }
            >
              Import {draft.contacts.length} contacts
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
