import { BookOpen, Zap } from "lucide-react";
import React from "react";
import { Badge, Empty, Modal } from "../../components/ui";
import { date } from "../../lib/format";
import { Row } from "../../lib/types";

type CallDetailsDialogProps = {
  call: Row;
  setCall: React.Dispatch<React.SetStateAction<Row | null>>;
};
export function CallDetailsDialog({ call, setCall }: CallDetailsDialogProps) {
  return (
    <Modal
      title="Conversation details"
      subtitle={`${call.direction} · ${date(call.created_at)}`}
      wide
      onClose={() => setCall(null)}
    >
      <div className="modal-content">
        <div className="call-summary">
          <Badge value={call.status} />
          <span>
            {call.outcome?.replaceAll("_", " ") || "No outcome recorded"}
          </span>
          <span>{call.to_number || "Browser simulator"}</span>
        </div>
        {call.error && <div className="alert error">{call.error}</div>}
        <div className="transcript">
          {call.events.map((e: Row) =>
            e.kind === "transcript" ? (
              <div
                key={e.id}
                className={
                  "transcript-message " +
                  (e.payload.speaker === "PATIENT" ? "patient" : "")
                }
              >
                <small>
                  {e.payload.speaker === "PATIENT" ? "Caller" : "Assistant"} ·{" "}
                  {date(e.created_at)}
                </small>
                <p>{e.payload.text}</p>
              </div>
            ) : e.kind === "tool" ? (
              <div className="transcript-event" key={e.id}>
                <Zap size={14} />
                {e.payload.action?.replaceAll("_", " ")} · {e.payload.outcome}
              </div>
            ) : e.kind === "knowledge_sources" && e.payload.sources?.length ? (
              <div className="transcript-event" key={e.id}>
                <BookOpen size={14} />
                Sources: {e.payload.sources.map((s: Row) => s.title).join(", ")}
              </div>
            ) : ["error", "tts_warning"].includes(e.kind) ? (
              <div className="transcript-event" key={e.id}>
                {e.payload.message}
              </div>
            ) : null,
          )}
          {!call.events.some((e: Row) => e.kind === "transcript") && (
            <Empty title="No transcript yet">
              Conversation events will appear here after the call starts.
            </Empty>
          )}
        </div>
      </div>
    </Modal>
  );
}
