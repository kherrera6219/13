import type { PersonaObjectionItem, PersonaSummary } from "../types/dle";
import "./components.css";

interface PersonaDrawerProps {
  persona: PersonaSummary | null;
  objections: PersonaObjectionItem[];
}

function capitalizeRole(roleName: string): string {
  if (!roleName) {
    return "Persona";
  }
  return roleName.charAt(0).toUpperCase() + roleName.slice(1);
}

export function PersonaDrawer({ persona, objections }: PersonaDrawerProps) {
  if (persona === null) {
    return (
      <section className="dle-panel-section" aria-label="Persona Inspection Drawer">
        <div className="dle-panel-header">
          <h3>Persona Detail</h3>
        </div>
        <p className="dle-muted">
          Select a persona chip to inspect findings, token allocation, and ledger objections.
        </p>
      </section>
    );
  }

  const findings = persona.findings ?? [];
  const roleObjections = objections.filter((o) => o.roleAxis === persona.roleAxis);

  return (
    <section className="dle-panel-section" aria-label="Persona Inspection Drawer">
      <div className="dle-panel-header">
        <h3>
          {capitalizeRole(persona.roleName)} (Axis {persona.roleAxis})
        </h3>
        <div className="dle-chip-flags">
          <span
            className={
              persona.valid
                ? "dle-status-tag dle-status-tag--supported"
                : "dle-status-tag dle-status-tag--contradicted"
            }
          >
            {persona.valid ? "Valid" : "Invalid"}
          </span>
          {persona.blinded && <span className="dle-status-tag">Blinded</span>}
          {persona.lowFit && (
            <span className="dle-status-tag dle-status-tag--weak">Low fit</span>
          )}
          {persona.falsificationEnabled && (
            <span className="dle-status-tag">Falsification</span>
          )}
        </div>
      </div>

      <dl className="dle-dl">
        <dt>Profile ID</dt>
        <dd className="dle-mono">{persona.profileId}</dd>
        <dt>Match M</dt>
        <dd className="dle-mono">{persona.mScore.toFixed(4)}</dd>
        <dt>Token Budget</dt>
        <dd className="dle-mono">{persona.tokenBudget}</dd>
        <dt>Claims</dt>
        <dd className="dle-mono">{persona.claimsCount}</dd>
        <dt>Objections</dt>
        <dd className="dle-mono">{persona.objectionsCount}</dd>
        <dt>Input SHA-256</dt>
        <dd className="dle-mono">{persona.inputSha256.slice(0, 16)}...</dd>
        <dt>Output SHA-256</dt>
        <dd className="dle-mono">{persona.outputSha256.slice(0, 16)}...</dd>
      </dl>

      <div className="dle-coord-block">
        <h4 className="dle-sub-heading">Findings</h4>
        {findings.length === 0 ? (
          <p className="dle-muted">No findings emitted.</p>
        ) : (
          <ul className="dle-citations-list">
            {findings.map((finding, idx) => (
              <li
                key={`${persona.profileId}-finding-${idx}`}
                className="dle-citation-item"
              >
                <div className="dle-timeline-row">
                  <span className="dle-status-tag">{finding.scope}</span>
                  {finding.passageIds.length > 0 && (
                    <span className="dle-mono dle-muted">
                      Sources: {finding.passageIds.join(", ")}
                    </span>
                  )}
                </div>
                <p className="dle-finding-text">{finding.assertion}</p>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="dle-coord-block">
        <h4 className="dle-sub-heading">Verifier Ledger Objections</h4>
        {roleObjections.length === 0 ? (
          <p className="dle-muted">No objections on ledger for this persona.</p>
        ) : (
          <ul className="dle-citations-list">
            {roleObjections.map((obj) => (
              <li key={obj.objectionId} className="dle-citation-item">
                <div className="dle-timeline-row">
                  <span className="dle-mono">{obj.objectionId}</span>
                  <span
                    className={
                      obj.blocking
                        ? "dle-status-tag dle-status-tag--contradicted"
                        : "dle-status-tag dle-status-tag--weak"
                    }
                  >
                    {obj.blocking ? "Blocking" : "Non-blocking"}
                  </span>
                  <span
                    className={
                      obj.state === "closed"
                        ? "dle-status-tag dle-status-tag--supported"
                        : "dle-status-tag dle-status-tag--weak"
                    }
                  >
                    {obj.state === "closed" ? "Closed by Verifier" : "Open"}
                  </span>
                </div>
                <p className="dle-finding-text dle-mono">{obj.predicate}</p>
                {obj.state === "closed" && obj.closureEvidence.length > 0 && (
                  <p className="dle-muted dle-mono">
                    Closure evidence: {obj.closureEvidence.join(", ")}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
