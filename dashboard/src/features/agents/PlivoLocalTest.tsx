import { useState } from "react";
import { z } from "zod";
import { Modal } from "../../components/ui";
import { api } from "../../lib/api";

const testSchema = z.object({
  call_id: z.string(),
  command: z.string(),
  expires_at: z.number(),
});

export function PlivoLocalTest({ agentId }: { agentId: string }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<z.infer<typeof testSchema> | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        className="button"
        disabled={busy}
        onClick={async () => {
          setOpen(true);
          setBusy(true);
          setError("");
          setResult(null);
          try {
            setResult(
              testSchema.parse(
                await api(`/agents/${agentId}/plivo-test`, "POST"),
              ),
            );
          } catch (e) {
            setError(
              e instanceof Error
                ? e.message
                : "Could not prepare the stream test.",
            );
          } finally {
            setBusy(false);
          }
        }}
      >
        Plivo stream test
      </button>
      {open && (
        <Modal
          title="Plivo local stream test"
          onClose={() => {
            setOpen(false);
            setResult(null);
          }}
        >
          <div className="modal-content">
            <p>
              Run this with the Plivo CLI on the computer hosting this
              development server. No phone number or telephone call is involved.
              This echoes the CLI’s synthetic tone to check audio transport and
              does not call speech or language providers.
            </p>
            {busy && <p role="status">Preparing a single-use test session…</p>}
            {error && (
              <p role="alert" className="field-error">
                {error}
              </p>
            )}
            {result && (
              <>
                <label>
                  Single-use command
                  <textarea
                    readOnly
                    rows={5}
                    value={result.command}
                    onFocus={(e) => e.target.select()}
                  />
                </label>
                <p>
                  Start before{" "}
                  {new Date(result.expires_at * 1000).toLocaleTimeString()}.
                  Keep the URL private. This verifies audio transport; use the
                  simulator for microphone conversations.
                </p>
              </>
            )}
          </div>
        </Modal>
      )}
    </>
  );
}
