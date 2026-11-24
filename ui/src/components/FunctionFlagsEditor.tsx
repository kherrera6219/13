import { type FormEvent, useEffect, useId, useState } from "react";
import type { ConsequentialFunctionItem } from "../types/dle";
import "./components.css";

interface FunctionFlagsEditorProps {
  flags: ConsequentialFunctionItem[];
  loading?: boolean;
  error?: string | null;
  statusMessage?: string | null;
  onSave: (nextFlags: ConsequentialFunctionItem[]) => Promise<void> | void;
}

export function FunctionFlagsEditor({
  flags,
  loading = false,
  error = null,
  statusMessage = null,
  onSave,
}: FunctionFlagsEditorProps) {
  const [items, setItems] = useState<ConsequentialFunctionItem[]>(flags);
  const [nameInput, setNameInput] = useState("");
  const [reasonInput, setReasonInput] = useState("");
  const [saving, setSaving] = useState(false);

  const nameId = useId();
  const reasonId = useId();

  useEffect(() => {
    setItems(flags);
  }, [flags]);

  const handleAdd = (e: FormEvent) => {
    e.preventDefault();
    const cleanName = nameInput.trim();
    const cleanReason = reasonInput.trim();
    if (!cleanName || !cleanReason) {
      return;
    }
    setItems((prev) => [
      ...prev.filter((item) => item.name !== cleanName),
      { name: cleanName, reason: cleanReason },
    ]);
    setNameInput("");
    setReasonInput("");
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(items);
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="dle-admin-panel" aria-label="Consequential Function Flags">
      <div className="dle-panel-header">
        <h2>Consequential Function Flags</h2>
        <span className="dle-status-tag">{items.length} flagged</span>
      </div>

      {error && (
        <div role="alert" className="dle-banner dle-banner--error">
          {error}
        </div>
      )}
      {statusMessage && (
        <div role="status" className="dle-banner dle-banner--ok">
          {statusMessage}
        </div>
      )}

      {items.length === 0 ? (
        <p className="dle-muted">
          No consequential functions flagged. Add tool names that require Regulator review.
        </p>
      ) : (
        <div className="dle-table-wrap">
          <table className="dle-table">
            <caption>Configured consequential client tools</caption>
            <thead>
              <tr>
                <th scope="col">Function Name</th>
                <th scope="col">Reason</th>
                <th scope="col">Action</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.name}>
                  <td className="dle-mono">{item.name}</td>
                  <td>{item.reason}</td>
                  <td>
                    <button
                      type="button"
                      className="dle-btn-secondary"
                      onClick={() =>
                        setItems((prev) => prev.filter((row) => row.name !== item.name))
                      }
                    >
                      Remove {item.name}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <form className="dle-admin-form" onSubmit={handleAdd}>
        <div className="dle-admin-grid">
          <label className="dle-field-label" htmlFor={nameId}>
            <span>Function Identifier</span>
            <input
              id={nameId}
              type="text"
              className="dle-input dle-mono"
              value={nameInput}
              placeholder="e.g. submit_purchase_order"
              onChange={(e) => setNameInput(e.target.value)}
            />
          </label>
          <label className="dle-field-label" htmlFor={reasonId}>
            <span>Review Reason</span>
            <input
              id={reasonId}
              type="text"
              className="dle-input"
              value={reasonInput}
              placeholder="e.g. Creates a binding financial commitment"
              onChange={(e) => setReasonInput(e.target.value)}
            />
          </label>
        </div>

        <div className="dle-chip-flags">
          <button
            type="submit"
            className="dle-btn-secondary"
            disabled={!nameInput.trim() || !reasonInput.trim()}
          >
            Add Flag
          </button>
          <button
            type="button"
            className="dle-btn-primary"
            disabled={loading || saving}
            onClick={() => void handleSave()}
          >
            {saving ? "Saving..." : "Save Flags"}
          </button>
        </div>
      </form>
    </section>
  );
}
