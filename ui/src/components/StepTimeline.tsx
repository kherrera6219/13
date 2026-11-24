import type { StepTraceItem } from "../types/dle";
import "./components.css";

interface StepTimelineProps {
  steps: StepTraceItem[];
  parkedToolName?: string;
}

export function StepTimeline({ steps, parkedToolName }: StepTimelineProps) {
  const retryAttempts = new Set(
    steps.filter((s) => s.event === "retry").map((s) => s.attemptId),
  );
  const escalationAttempts = new Set(
    steps.filter((s) => s.event === "tier_escalation").map((s) => s.attemptId),
  );

  return (
    <section className="dle-panel-section" aria-label="Execution Step Timeline">
      <div className="dle-panel-header">
        <h3>Execution Steps</h3>
        <div className="dle-chip-flags">
          <span className="dle-status-tag">{steps.length} steps</span>
          {retryAttempts.size > 0 && (
            <span className="dle-status-tag dle-status-tag--weak">
              {retryAttempts.size} {retryAttempts.size === 1 ? "retry" : "retries"}
            </span>
          )}
          {escalationAttempts.size > 0 && (
            <span className="dle-status-tag dle-status-tag--weak">
              {escalationAttempts.size} escalated
            </span>
          )}
          {parkedToolName && (
            <span className="dle-status-tag dle-badge--tool_call">Parked on tool call</span>
          )}
        </div>
      </div>

      {parkedToolName && (
        <div role="status" className="dle-step-park-banner">
          Parked at Step 4 waiting for client tool call:{" "}
          <span className="dle-mono">{parkedToolName}</span>
        </div>
      )}

      {steps.length === 0 && !parkedToolName ? (
        <p className="dle-muted">No step trace recorded for this run.</p>
      ) : (
        <ol className="dle-timeline">
          {steps.map((s, idx) => (
            <li
              key={`${s.attemptId}-${s.stepId}-${s.layerId}-${idx}`}
              className="dle-timeline-item"
            >
              <div className="dle-timeline-row">
                <span className="dle-mono dle-timeline-step">{s.stepId}</span>
                <span className="dle-mono dle-muted">{s.layerId}</span>
                <span className="dle-mono dle-timeline-attempt">{s.attemptId}</span>
                <span className="dle-status-tag">{s.event}</span>
                <span className="dle-status-tag">{s.status}</span>
                <span className="dle-mono dle-muted">{s.durationMs.toFixed(1)} ms</span>
              </div>
              {s.dvssIds.length > 0 && (
                <div className="dle-mono dle-muted">
                  Functions: {s.dvssIds.join(", ")}
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
