import type { ReleaseMode, RunSummary } from "../types/dle";
import "./components.css";

interface RunSummaryCardProps {
  runSummary: RunSummary | null;
  releaseMode?: ReleaseMode | null;
  terminalU?: number | null;
}

export function RunSummaryCard({
  runSummary,
  releaseMode = null,
  terminalU = null,
}: RunSummaryCardProps) {
  if (runSummary === null) {
    return (
      <section className="dle-panel-section" aria-label="Run Summary">
        <div className="dle-panel-header">
          <h3>Run Summary</h3>
        </div>
        <p className="dle-muted">
          Send a governed query to inspect tier selection, retries, and persona summary.
        </p>
      </section>
    );
  }

  const tierText = runSummary.escalated
    ? `Tier ${runSummary.initialTier} -> Tier ${runSummary.finalTier} (Escalated)`
    : `Tier ${runSummary.finalTier}`;

  return (
    <section className="dle-panel-section" aria-label="Run Summary">
      <div className="dle-panel-header">
        <h3>Run Summary</h3>
        <div className="dle-chip-flags">
          {runSummary.escalated && (
            <span className="dle-status-tag dle-status-tag--weak">Escalated</span>
          )}
          {releaseMode && (
            <span className="dle-status-tag dle-mono">{releaseMode}</span>
          )}
        </div>
      </div>

      <dl className="dle-dl">
        <dt>Tier</dt>
        <dd className="dle-mono">{tierText}</dd>
        {runSummary.escalationReason && (
          <>
            <dt>Escalation Reason</dt>
            <dd className="dle-mono">{runSummary.escalationReason}</dd>
          </>
        )}
        <dt>Retries</dt>
        <dd className="dle-mono">
          {runSummary.retries} / {runSummary.maxRetries}
        </dd>
        <dt>Attempts</dt>
        <dd className="dle-mono">{runSummary.attemptsCount}</dd>
        <dt>Assurance Ordering</dt>
        <dd>{runSummary.blindedAssuranceRoles ? "Blinded" : "Standard"}</dd>
        {runSummary.sEff !== undefined && (
          <>
            <dt>Intake S_eff</dt>
            <dd className="dle-mono">{runSummary.sEff}</dd>
          </>
        )}
        {runSummary.modelCallsUsed !== undefined && runSummary.modelCallBudget !== undefined && (
          <>
            <dt>Model Calls</dt>
            <dd className="dle-mono">
              {runSummary.modelCallsUsed} / {runSummary.modelCallBudget}
            </dd>
          </>
        )}
        {runSummary.costUsd !== undefined && (
          <>
            <dt>Metered Cost</dt>
            <dd className="dle-mono">${runSummary.costUsd.toFixed(6)}</dd>
          </>
        )}
        {terminalU !== undefined && terminalU !== null && (
          <>
            <dt>Terminal u</dt>
            <dd className="dle-mono">{terminalU.toFixed(4)}</dd>
          </>
        )}
        {runSummary.consequentialTools.length > 0 && (
          <>
            <dt>Consequential Tools</dt>
            <dd className="dle-mono">{runSummary.consequentialTools.join(", ")}</dd>
          </>
        )}
      </dl>
    </section>
  );
}
