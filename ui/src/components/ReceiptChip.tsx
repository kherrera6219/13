import { useState } from "react";
import type { ReceiptStatus } from "../types/dle";
import "./components.css";

interface ReceiptChipProps {
  receiptId: string;
  status?: ReceiptStatus;
}

export function ReceiptChip({ receiptId, status = "sealed" }: ReceiptChipProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(receiptId);
      }
    } catch {
      // Clipboard API may be unavailable in non-secure contexts; feedback still indicates attempt.
    }
    setCopied(true);
  };

  const shortId = receiptId.length > 13 ? `${receiptId.slice(0, 8)}...` : receiptId;
  const statusLabel = status === "sealed" ? "Sealed" : "Pending anchor";

  return (
    <span className="dle-receipt">
      <span>{statusLabel}</span>
      <code className="dle-receipt-id" title={receiptId}>
        {shortId}
      </code>
      <button
        type="button"
        className="dle-receipt-btn"
        onClick={() => void handleCopy()}
        aria-label={`Copy receipt ID ${receiptId}`}
      >
        Copy
      </button>
      <span aria-live="polite" className="dle-receipt-feedback">
        {copied ? "Copied" : ""}
      </span>
    </span>
  );
}
