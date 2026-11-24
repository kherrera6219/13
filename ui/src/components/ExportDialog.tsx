import { type FormEvent, useId, useState } from "react";
import "./components.css";

interface ExportDialogProps {
  onExport: (fromIso: string, toIso: string) => Promise<void> | void;
  initialState?: "idle" | "building" | "done" | "error";
  initialError?: string | null;
  initialFrom?: string;
  initialTo?: string;
}

export function ExportDialog({
  onExport,
  initialState = "idle",
  initialError = null,
  initialFrom = "2026-11-01T00:00:00Z",
  initialTo = "2026-11-30T23:59:59Z",
}: ExportDialogProps) {
  const [fromIso, setFromIso] = useState(initialFrom);
  const [toIso, setToIso] = useState(initialTo);
  const [state, setState] = useState<"idle" | "building" | "done" | "error">(initialState);
  const [errorMsg, setErrorMsg] = useState<string | null>(initialError);

  const fromId = useId();
  const toId = useId();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!fromIso.trim() || !toIso.trim()) {
      return;
    }
    setState("building");
    setErrorMsg(null);
    try {
      await onExport(fromIso.trim(), toIso.trim());
      setState("done");
    } catch (err) {
      setState("error");
      setErrorMsg(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <section className="dle-admin-panel" aria-label="Signed Receipt Export">
      <div className="dle-panel-header">
        <h2>Receipt Bundle Export</h2>
      </div>

      <form className="dle-admin-form" onSubmit={(e) => void handleSubmit(e)}>
        <div className="dle-admin-grid">
          <label className="dle-field-label" htmlFor={fromId}>
            <span>From (UTC ISO-8601)</span>
            <input
              id={fromId}
              type="text"
              className="dle-input dle-mono"
              value={fromIso}
              onChange={(e) => setFromIso(e.target.value)}
            />
          </label>
          <label className="dle-field-label" htmlFor={toId}>
            <span>To (UTC ISO-8601)</span>
            <input
              id={toId}
              type="text"
              className="dle-input dle-mono"
              value={toIso}
              onChange={(e) => setToIso(e.target.value)}
            />
          </label>
        </div>

        <div className="dle-chip-flags">
          <button
            type="submit"
            className="dle-btn-primary"
            disabled={state === "building" || !fromIso.trim() || !toIso.trim()}
          >
            {state === "building" ? "Building bundle..." : "Export Receipt Bundle"}
          </button>
        </div>

        {state === "building" && (
          <p role="status" className="dle-muted">
            Building signed Merkle bundle...
          </p>
        )}
        {state === "done" && (
          <div role="status" className="dle-banner dle-banner--ok">
            Receipt bundle exported.
          </div>
        )}
        {state === "error" && (
          <div role="alert" className="dle-banner dle-banner--error">
            {errorMsg ?? "Receipt bundle export failed."}
          </div>
        )}
      </form>
    </section>
  );
}
