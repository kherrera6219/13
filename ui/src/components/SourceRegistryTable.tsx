import { useId, useState, type FormEvent } from "react";
import type { RegisterSourceInput } from "../lib/dleClient";
import type { EvidenceSource } from "../types/dle";
import "./components.css";

interface SourceRegistryTableProps {
  sources: EvidenceSource[];
  loading?: boolean;
  onRefresh?: () => void;
  onRegister?: (input: RegisterSourceInput) => Promise<void> | void;
}

const AUTHORITY_OPTIONS = [
  { value: "primary_text", label: "primary_text (prior 1.00)" },
  { value: "binding_instrument", label: "binding_instrument (prior 0.95)" },
  { value: "official_guidance", label: "official_guidance (prior 0.70)" },
  { value: "industry_practice", label: "industry_practice (prior 0.45)" },
  { value: "commentary", label: "commentary (prior 0.25)" },
];

export function SourceRegistryTable({
  sources,
  loading = false,
  onRefresh,
  onRegister,
}: SourceRegistryTableProps) {
  const [title, setTitle] = useState("");
  const [authorityClass, setAuthorityClass] = useState("primary_text");
  const [jurisdiction, setJurisdiction] = useState("");
  const [contentText, setContentText] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const titleId = useId();
  const authorityId = useId();
  const jurisdictionId = useId();
  const contentId = useId();

  const handleSubmit = async (evt: FormEvent) => {
    evt.preventDefault();
    if (!title.trim() || !contentText.trim() || !onRegister) {
      return;
    }
    setSubmitting(true);
    try {
      await onRegister({
        title: title.trim(),
        authorityClass,
        jurisdiction: jurisdiction.trim() || undefined,
        contentText: contentText.trim(),
      });
      setTitle("");
      setJurisdiction("");
      setContentText("");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="dle-admin-panel" aria-label="Evidence Source Registry">
      {onRegister && (
        <form className="dle-admin-form" onSubmit={(e) => void handleSubmit(e)}>
          <div className="dle-panel-header">
            <h3>Register Evidence Source</h3>
          </div>
          <div className="dle-admin-grid">
            <label className="dle-field-label" htmlFor={titleId}>
              <span>Title</span>
              <input
                id={titleId}
                type="text"
                className="dle-input"
                value={title}
                placeholder="e.g. Warehouse Valve Spec v2"
                onChange={(e) => setTitle(e.target.value)}
                disabled={submitting}
              />
            </label>
            <label className="dle-field-label" htmlFor={authorityId}>
              <span>Authority Class</span>
              <select
                id={authorityId}
                className="dle-select"
                value={authorityClass}
                onChange={(e) => setAuthorityClass(e.target.value)}
                disabled={submitting}
              >
                {AUTHORITY_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="dle-field-label" htmlFor={jurisdictionId}>
              <span>Jurisdiction (optional)</span>
              <input
                id={jurisdictionId}
                type="text"
                className="dle-input"
                value={jurisdiction}
                placeholder="e.g. US-FEDERAL"
                onChange={(e) => setJurisdiction(e.target.value)}
                disabled={submitting}
              />
            </label>
          </div>
          <label className="dle-field-label" htmlFor={contentId}>
            <span>Document Text</span>
            <textarea
              id={contentId}
              className="dle-textarea"
              value={contentText}
              placeholder="Paste authoritative text clauses to ingest into SQLite evidence store..."
              onChange={(e) => setContentText(e.target.value)}
              disabled={submitting}
            />
          </label>
          <div>
            <button
              type="submit"
              className="dle-btn-primary"
              disabled={submitting || !title.trim() || !contentText.trim()}
            >
              {submitting ? "Registering..." : "Register Source"}
            </button>
          </div>
        </form>
      )}

      <div className="dle-admin-form">
        <div className="dle-panel-header">
          <h3>Registered Sources ({sources.length})</h3>
          {onRefresh && (
            <button type="button" className="dle-btn-secondary" onClick={onRefresh} disabled={loading}>
              {loading ? "Refreshing..." : "Refresh sources"}
            </button>
          )}
        </div>

        {sources.length === 0 ? (
          <p className="dle-muted">
            No evidence sources registered yet. Governed strict queries will hold until qualifying sources exist.
          </p>
        ) : (
          <div className="dle-table-wrap">
            <table className="dle-table">
              <caption>Active evidence corpus records</caption>
              <thead>
                <tr>
                  <th scope="col">Title</th>
                  <th scope="col">Authority</th>
                  <th scope="col">Jurisdiction</th>
                  <th scope="col">Window</th>
                  <th scope="col">Retainable</th>
                  <th scope="col">Digest</th>
                </tr>
              </thead>
              <tbody>
                {sources.map((src) => (
                  <tr key={src.sourceId}>
                    <td>{src.title}</td>
                    <td className="dle-mono">{src.authorityClass}</td>
                    <td>{src.jurisdiction ?? "—"}</td>
                    <td className="dle-mono">
                      {src.validFrom ?? "open"} to {src.validTo ?? "open"}
                    </td>
                    <td>{src.retainable ? "Yes" : "No"}</td>
                    <td className="dle-mono">{src.contentSha256.slice(0, 12)}...</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
