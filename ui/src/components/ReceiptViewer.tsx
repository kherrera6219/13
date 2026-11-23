import { useState } from "react";
import type { SignedReceipt } from "../types/dle";
import "./components.css";

interface ReceiptViewerProps {
  receipt: SignedReceipt | null;
}

export function ReceiptViewer({ receipt }: ReceiptViewerProps) {
  const [copied, setCopied] = useState(false);

  if (receipt === null) {
    return (
      <section className="dle-panel-section" aria-label="Cryptographic receipt inspector">
        <div className="dle-panel-header">
          <h3>Signed Receipt</h3>
        </div>
        <p className="dle-muted">Send a governed request to inspect its signed 3.8.0 receipt.</p>
      </section>
    );
  }

  const { payload, envelope } = receipt;

  const handleCopyJson = async () => {
    const serialized = JSON.stringify(receipt, null, 2);
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard) {
        await navigator.clipboard.writeText(serialized);
      }
      setCopied(true);
    } catch {
      setCopied(true);
    }
  };

  return (
    <section className="dle-panel-section" aria-label="Cryptographic receipt inspector">
      <div className="dle-panel-header">
        <h3>Signed Receipt ({payload.schema_version})</h3>
        <button type="button" className="dle-receipt-btn" onClick={() => void handleCopyJson()}>
          {copied ? "Copied JSON" : "Copy JSON"}
        </button>
      </div>

      <dl className="dle-dl">
        <dt>Run Decision</dt>
        <dd className="dle-mono">{payload.decision.release_mode}</dd>
        <dt>Terminal u</dt>
        <dd className="dle-mono">{payload.decision.terminal_u.toFixed(4)}</dd>
        <dt>CUSUM / Drift</dt>
        <dd className="dle-mono">
          {payload.decision.cusum.toFixed(3)} ({payload.decision.drift_latched ? "latched" : "clear"})
        </dd>
        <dt>Signing Key</dt>
        <dd className="dle-mono">
          {envelope.key_id} ({envelope.algorithm})
        </dd>
        <dt>Inclusion Proof</dt>
        <dd className="dle-mono">{envelope.inclusion_proof_ref}</dd>
        <dt>Kernel Calls</dt>
        <dd className="dle-mono">{payload.function_invocations.length}</dd>
        <dt>Receipt Digest</dt>
        <dd className="dle-mono">{envelope.digest_sha256.slice(0, 16)}...</dd>
        <dt>Response SHA-256</dt>
        <dd className="dle-mono">{payload.response_sha256.slice(0, 16)}...</dd>
      </dl>

      <details>
        <summary className="dle-citation-toggle">Raw 3.8.0 Receipt JSON</summary>
        <pre className="dle-pre dle-mono">{JSON.stringify(receipt, null, 2)}</pre>
      </details>
    </section>
  );
}
