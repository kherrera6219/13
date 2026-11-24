import type { CostByTierDay } from "../types/dle";
import "./components.css";

interface CostByTierChartProps {
  days: CostByTierDay[];
  loading?: boolean;
  onRefresh?: () => void;
}

export function CostByTierChart({ days, loading = false, onRefresh }: CostByTierChartProps) {
  const maxDayTotal = Math.max(
    0.0001,
    ...days.map((d) => (d.totalUsd > 0 ? d.totalUsd : 0)),
  );

  return (
    <section className="dle-admin-panel" aria-label="Cost by Tier">
      <div className="dle-panel-header">
        <h2>Cost by Tier</h2>
        {onRefresh && (
          <button
            type="button"
            className="dle-btn-secondary"
            disabled={loading}
            onClick={onRefresh}
          >
            {loading ? "Loading..." : "Refresh Cost Metrics"}
          </button>
        )}
      </div>

      {days.length === 0 ? (
        <p className="dle-muted">
          No metered cost data recorded yet. Run governed requests to populate spend by tier.
        </p>
      ) : (
        <>
          <div className="dle-cost-legend" aria-label="Tier spend legend">
            <span className="dle-legend-item">
              <span className="dle-legend-swatch dle-legend-swatch--t1" aria-hidden="true" />
              Tier 1
            </span>
            <span className="dle-legend-item">
              <span className="dle-legend-swatch dle-legend-swatch--t2" aria-hidden="true" />
              Tier 2
            </span>
            <span className="dle-legend-item">
              <span className="dle-legend-swatch dle-legend-swatch--t3" aria-hidden="true" />
              Tier 3
            </span>
          </div>

          <div className="dle-cost-bars" role="region" aria-label="Daily spend bars">
            {days.map((day) => {
              const t1Pct = (day.tier1Usd / maxDayTotal) * 100;
              const t2Pct = (day.tier2Usd / maxDayTotal) * 100;
              const t3Pct = (day.tier3Usd / maxDayTotal) * 100;
              const isSpike = day.totalUsd > 0 && day.tier3Usd / day.totalUsd >= 0.6;
              return (
                <div key={day.date} className="dle-cost-bar-row">
                  <span className="dle-mono dle-cost-date">{day.date}</span>
                  <div className="dle-cost-track" aria-hidden="true">
                    <span
                      className="dle-cost-seg dle-cost-seg--t1"
                      style={{ width: `${t1Pct.toFixed(1)}%` }}
                    />
                    <span
                      className="dle-cost-seg dle-cost-seg--t2"
                      style={{ width: `${t2Pct.toFixed(1)}%` }}
                    />
                    <span
                      className="dle-cost-seg dle-cost-seg--t3"
                      style={{ width: `${t3Pct.toFixed(1)}%` }}
                    />
                  </div>
                  <span className="dle-mono">${day.totalUsd.toFixed(4)}</span>
                  {isSpike && (
                    <span className="dle-status-tag dle-status-tag--weak">Tier 3 spike</span>
                  )}
                </div>
              );
            })}
          </div>

          <div className="dle-table-wrap">
            <table className="dle-table">
              <caption>Daily USD spend and run counts by tier</caption>
              <thead>
                <tr>
                  <th scope="col">Date</th>
                  <th scope="col">Tier 1</th>
                  <th scope="col">Tier 2</th>
                  <th scope="col">Tier 3</th>
                  <th scope="col">Total USD</th>
                  <th scope="col">Runs</th>
                </tr>
              </thead>
              <tbody>
                {days.map((day) => {
                  const totalRuns =
                    (day.runsByTier["1"] ?? 0) +
                    (day.runsByTier["2"] ?? 0) +
                    (day.runsByTier["3"] ?? 0);
                  return (
                    <tr key={`row-${day.date}`}>
                      <td className="dle-mono">{day.date}</td>
                      <td className="dle-mono">${day.tier1Usd.toFixed(4)}</td>
                      <td className="dle-mono">${day.tier2Usd.toFixed(4)}</td>
                      <td className="dle-mono">${day.tier3Usd.toFixed(4)}</td>
                      <td className="dle-mono">${day.totalUsd.toFixed(4)}</td>
                      <td className="dle-mono">{totalRuns}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
