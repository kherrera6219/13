import type { PersonaSummary } from "../types/dle";
import "./components.css";

interface PersonaChipsProps {
  personas: PersonaSummary[];
  selectedRoleAxis: number | null;
  onSelectPersona: (roleAxis: number) => void;
}

function capitalizeRole(roleName: string): string {
  if (!roleName) {
    return "Persona";
  }
  return roleName.charAt(0).toUpperCase() + roleName.slice(1);
}

export function PersonaChips({
  personas,
  selectedRoleAxis,
  onSelectPersona,
}: PersonaChipsProps) {
  return (
    <section className="dle-panel-section" aria-label="Active Personas">
      <div className="dle-panel-header">
        <h3>Active Personas</h3>
        <span className="dle-status-tag">{personas.length} active</span>
      </div>

      {personas.length === 0 ? (
        <p className="dle-muted">No personas invoked for this run.</p>
      ) : (
        <div className="dle-chip-group" role="group" aria-label="Active personas">
          {personas.map((p) => {
            const isSelected = selectedRoleAxis === p.roleAxis;
            return (
              <button
                key={`${p.roleAxis}-${p.profileId}`}
                type="button"
                className={
                  isSelected
                    ? "dle-persona-chip dle-persona-chip--selected"
                    : "dle-persona-chip"
                }
                aria-pressed={isSelected}
                onClick={() => onSelectPersona(p.roleAxis)}
              >
                <span className="dle-persona-chip-top">
                  <strong>{capitalizeRole(p.roleName)}</strong>
                  <span className="dle-mono dle-muted">Axis {p.roleAxis}</span>
                </span>
                <span className="dle-mono dle-chip-meta">
                  {p.profileId} · M={p.mScore.toFixed(2)} · {p.tokenBudget} tok
                </span>
                {(p.blinded || p.lowFit || p.falsificationEnabled || p.objectionsCount > 0) && (
                  <span className="dle-chip-flags">
                    {p.blinded && <span className="dle-status-tag">Blinded</span>}
                    {p.lowFit && (
                      <span className="dle-status-tag dle-status-tag--weak">Low fit</span>
                    )}
                    {p.falsificationEnabled && (
                      <span className="dle-status-tag">Falsification</span>
                    )}
                    {p.objectionsCount > 0 && (
                      <span className="dle-status-tag dle-status-tag--contradicted">
                        {p.objectionsCount}{" "}
                        {p.objectionsCount === 1 ? "objection" : "objections"}
                      </span>
                    )}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}
