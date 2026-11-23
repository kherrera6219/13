import type { ChatRun } from "../types/dle";
import { CitationList } from "./CitationList";
import { ReceiptChip } from "./ReceiptChip";
import { ReleaseBadge } from "./ReleaseBadge";
import "./components.css";

interface MessageBubbleProps {
  run: ChatRun;
  selected?: boolean;
  onSelectReceipt?: (run: ChatRun) => void;
}

export function MessageBubble({ run, selected = false, onSelectReceipt }: MessageBubbleProps) {
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
  const selectedModifier = selected ? " dle-bubble--selected" : "";

  return (
    <article
      className={`dle-bubble${modeModifier}${selectedModifier}`}
      aria-label="Assistant response"
    >
      <div className="dle-bubble-header">
        <ReleaseBadge mode={run.releaseMode} />
        {run.tier !== null && <span className="dle-bubble-meta">Tier {run.tier}</span>}
        <span className="dle-bubble-meta dle-mono">{run.model}</span>
        {run.receiptId && <ReceiptChip receiptId={run.receiptId} status={run.receiptStatus} />}
        {run.receiptId && onSelectReceipt && (
          <button
            type="button"
            className="dle-receipt-btn"
            aria-pressed={selected}
            onClick={() => onSelectReceipt(run)}
          >
            {selected ? "Inspecting" : "Inspect run"}
          </button>
        )}
      </div>

      <p className="dle-bubble-body">{run.text}</p>

      {run.citations && run.citations.length > 0 && <CitationList citations={run.citations} />}

      <p role="status" className="dle-bubble-notice">
        {run.noticeText}
      </p>
    </article>
  );
}
