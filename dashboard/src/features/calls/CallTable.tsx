import {
  ArrowDownLeft,
  ArrowRight,
  ArrowUpRight,
  AudioLines,
} from "lucide-react";
import { Badge } from "../../components/ui";
import { date } from "../../lib/format";
import type { Row } from "../../lib/types";
export function CallTable({
  rows,
  agents,
  open,
}: {
  rows: Row[];
  agents: Row[];
  open: (id: string) => void;
}) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Agent / contact</th>
            <th>Channel</th>
            <th>Status</th>
            <th>Started</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.id}>
              <td>
                <strong>
                  {c.agent_name ||
                    agents.find((a) => a.id === c.agent_id)?.name ||
                    "Agent"}
                </strong>
                <small>
                  {c.to_number || c.from_number || "Browser conversation"}
                </small>
              </td>
              <td>
                <span className="channel">
                  {c.direction === "inbound" ? (
                    <ArrowDownLeft size={15} />
                  ) : c.direction === "outbound" ? (
                    <ArrowUpRight size={15} />
                  ) : (
                    <AudioLines size={15} />
                  )}{" "}
                  {c.direction}
                </span>
              </td>
              <td>
                <Badge value={c.status} />
              </td>
              <td>{date(c.created_at)}</td>
              <td>
                <button
                  className="icon-button"
                  aria-label="View call details"
                  onClick={() => open(c.id)}
                >
                  <ArrowRight size={17} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
