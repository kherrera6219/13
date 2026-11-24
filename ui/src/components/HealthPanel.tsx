import type { HealthStatus } from "../types/dle";
import "./components.css";

interface HealthPanelProps {
  health: HealthStatus | null;
  error?: string | null;
  onRefresh?: () => void;
}

export function HealthPanel({ health, error = null, onRefresh }: HealthPanelProps) {
  return (
    <section className="dle-admin-panel" aria-label="Middleware Health Panel">
      <div className="dle-panel-header">
        <h2>System Health</h2>
        <div className="dle-chip-flags">
          {health && (
            <span
              className={
                health.status === "ok"
                  ? "dle-status-tag dle-status-tag--supported"
                  : "dle-status-tag dle-status-tag--weak"
              }
            >
              {health.status === "ok" ? "All green" : "Degraded"}
            </span>
          )}
          {onRefresh && (
            <button type="button" className="dle-btn-secondary" onClick={onRefresh}>
              Refresh Health
            </button>
          )}
        </div>
      </div>

      {error && (
        <div role="alert" className="dle-banner dle-banner--error">
          {error}
        </div>
      )}

      {health === null ? (
        <p className="dle-muted">Health telemetry not loaded yet.</p>
      ) : (
        <dl className="dle-dl">
          <dt>Status</dt>
          <dd className="dle-mono">{health.status}</dd>
          <dt>Bind Address</dt>
          <dd className="dle-mono">{health.bind}</dd>
          <dt>Model Backend</dt>
          <dd>
            <span
              className={
                health.modelReachable
                  ? "dle-status-tag dle-status-tag--supported"
                  : "dle-status-tag dle-status-tag--contradicted"
              }
            >
              {health.modelReachable ? "Reachable" : "Model unreachable"}
            </span>
          </dd>
          <dt>Independent NLI</dt>
          <dd>
            <span
              className={
                health.nliLoaded
                  ? "dle-status-tag dle-status-tag--supported"
                  : "dle-status-tag dle-status-tag--weak"
              }
            >
              {health.nliLoaded ? "Loaded" : "NLI not loaded"}
            </span>
          </dd>
          <dt>Drift Latch</dt>
          <dd>
            <span
              className={
                health.driftLatch === "clear"
                  ? "dle-status-tag dle-status-tag--supported"
                  : "dle-status-tag dle-status-tag--contradicted"
              }
            >
              {health.driftLatch === "clear" ? "Clear" : "Drift latch tripped"}
            </span>
          </dd>
          <dt>Kernel Functions</dt>
          <dd className="dle-mono">{health.kernelFunctions}</dd>
          <dt>Version</dt>
          <dd className="dle-mono">{health.version}</dd>
        </dl>
      )}
    </section>
  );
}
