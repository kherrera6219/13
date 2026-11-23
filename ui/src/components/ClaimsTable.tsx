import { useState } from "react";
import type { ClaimRow, ClaimStatus } from "../types/dle";
import "./components.css";

interface ClaimsTableProps {
  claims: ClaimRow[];
}

const STATUS_LABELS: Record<ClaimStatus, string> = {
  supported: "Supported",
  weak: "Weak support",
  contradicted: "Contradicted",
  unverified: "Unverified",
};

export function ClaimsTable({ claims }: ClaimsTableProps) {
  const [sortWeakestFirst, setSortWeakestFirst] = useState(true);

  if (claims.length === 0) {
    return (
      <section className="dle-panel-section" aria-label="Claims verification table">
        <div className="dle-panel-header">
          <h3>Claims</h3>
        </div>
        <p className="dle-muted">No extracted claims recorded yet for this run.</p>
      </section>
    );
  }

  const ordered = sortWeakestFirst
    ? [...claims].sort((a, b) => a.supportZ - b.supportZ)
    : claims;

  return (
    <section className="dle-panel-section" aria-label="Claims verification table">
      <div className="dle-panel-header">
        <h3>Claims ({claims.length})</h3>
        <button
          type="button"
          className="dle-receipt-btn"
          onClick={() => setSortWeakestFirst((prev) => !prev)}
        >
          {sortWeakestFirst ? "Order: weakest first" : "Order: draft sequence"}
        </button>
      </div>

      <div className="dle-table-wrap">
        <table className="dle-table">
          <caption>Claim support and status breakdown</caption>
          <thead>
            <tr>
              <th scope="col">Claim</th>
              <th scope="col">Support</th>
              <th scope="col">Contra</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {ordered.map((claim) => (
              <tr key={claim.claimId}>
                <td>
                  <div>{claim.assertion}</div>
                  <div className="dle-muted">
                    {claim.binding ? "Binding" : "Informational"} · {claim.sourceIds.length} source(s)
                  </div>
                </td>
                <td className="dle-mono">{claim.supportZ.toFixed(2)}</td>
                <td className="dle-mono">{claim.contradictionZ.toFixed(2)}</td>
                <td>
                  <span className={`dle-status-tag dle-status-tag--${claim.status}`}>
                    {STATUS_LABELS[claim.status]}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
