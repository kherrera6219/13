import type { ChatRun } from "../types/dle";
import { ReceiptChip } from "./ReceiptChip";
import { ReleaseBadge } from "./ReleaseBadge";
import "./components.css";

interface MessageBubbleProps {
  run: ChatRun;
}

export function MessageBubble({ run }: MessageBubbleProps) {
  if (run.role === "user") {
    return (
      <article className="dle-bubble dle-bubble--user" aria-label="User prompt">
        <div className="dle-bubble-header">
          <span className="dle-bubble-meta">You</span>
          <span className="dle-bubble-meta dle-mono">{run.model}</span>
        </div>
        <p className="dle-bubble-body">{run.text}</p>
      </article>
    );
  }

  const modeModifier =
    run.releaseMode === "held"
      ? " dle-bubble--held"
      : run.releaseMode === "error"
        ? " dle-bubble--error"
        : "";

  return (
    <article className={`dle-bubble${modeModifier}`} aria-label="Assistant response">
      <div className="dle-bubble-header">
        <ReleaseBadge mode={run.releaseMode} />
        {run.tier !== null && <span className="dle-bubble-meta">Tier {run.tier}</span>}
        <span className="dle-bubble-meta dle-mono">{run.model}</span>
        {run.receiptId && <ReceiptChip receiptId={run.receiptId} status={run.receiptStatus} />}
      </div>

      <p className="dle-bubble-body">{run.text}</p>

      <p role="status" className="dle-bubble-notice">
        {run.noticeText}
      </p>
    </article>
  );
}
