import type { CoordinateSummary, GraphSummary } from "../types/dle";
import "./components.css";

interface AddressGraphDrawerProps {
  coordinate: CoordinateSummary | null;
  graph: GraphSummary | null;
}

export function AddressGraphDrawer({ coordinate, graph }: AddressGraphDrawerProps) {
  if (coordinate === null && graph === null) {
    return (
      <section className="dle-panel-section" aria-label="13-Axis Coordinate and Graph Drawer">
        <div className="dle-panel-header">
          <h3>13-Axis Address &amp; Graph</h3>
        </div>
        <p className="dle-muted">
          Send a governed query to inspect its 13-axis coordinate and bounded PPR graph.
        </p>
      </section>
    );
  }

  return (
    <section className="dle-panel-section" aria-label="13-Axis Coordinate and Graph Drawer">
      <div className="dle-panel-header">
        <h3>13-Axis Address &amp; Graph</h3>
        {graph !== null && (
          <span
            className={
              graph.pprEnabled
                ? "dle-status-tag dle-status-tag--supported"
                : "dle-status-tag dle-status-tag--weak"
            }
          >
            {graph.pprEnabled ? "PPR active" : "Dense retrieval only"}
          </span>
        )}
      </div>

      {coordinate !== null && (
        <div className="dle-coord-block">
          <dl className="dle-dl">
            <dt>Manifest SHA</dt>
            <dd className="dle-mono">{coordinate.manifestSha256.slice(0, 16)}...</dd>
            <dt>Jurisdiction</dt>
            <dd className="dle-mono">{coordinate.jurisdictionState}</dd>
            <dt>Active Axes</dt>
            <dd className="dle-mono">{coordinate.activeAxes.join(", ")}</dd>
            <dt>Active Roles</dt>
            <dd>{coordinate.activatedRoles.join(", ")}</dd>
          </dl>

          <details>
            <summary className="dle-citation-toggle">
              Coordinate Atoms ({Object.keys(coordinate.atomsByAxis).length} axes)
            </summary>
            <dl className="dle-dl">
              {Object.entries(coordinate.atomsByAxis).map(([axisKey, atoms]) => (
                <div key={axisKey} className="dle-axis-row">
                  <dt className="dle-mono">{axisKey}</dt>
                  <dd className="dle-mono">{atoms.join(", ")}</dd>
                </div>
              ))}
            </dl>
          </details>
        </div>
      )}

      {graph !== null && (
        <div className="dle-coord-block">
          <dl className="dle-dl">
            <dt>Hop Budget</dt>
            <dd className="dle-mono">{graph.hops}</dd>
            <dt>PPR Iterations</dt>
            <dd className="dle-mono">{graph.pprIterations}</dd>
            <dt>Vertices Retained</dt>
            <dd className="dle-mono">{graph.verticesRetained}</dd>
            <dt>Graph SHA-256</dt>
            <dd className="dle-mono">{graph.graphSha256.slice(0, 16)}...</dd>
          </dl>

          {graph.nodes.length > 0 && (
            <div className="dle-table-wrap">
              <table className="dle-table">
                <caption>Ranked bounded PPR vertices</caption>
                <thead>
                  <tr>
                    <th scope="col">Vertex</th>
                    <th scope="col">Hop</th>
                    <th scope="col">Mass</th>
                    <th scope="col">Kind</th>
                  </tr>
                </thead>
                <tbody>
                  {graph.nodes.map((node) => (
                    <tr key={node.vertexId}>
                      <td className="dle-mono">{node.vertexId}</td>
                      <td className="dle-mono">{node.hop}</td>
                      <td className="dle-mono">{node.score.toFixed(4)}</td>
                      <td>
                        <span
                          className={
                            node.synthetic
                              ? "dle-status-tag dle-status-tag--weak"
                              : "dle-status-tag dle-status-tag--supported"
                          }
                        >
                          {node.synthetic ? "Hypothesis only" : "Canonical"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {graph.edges.length > 0 && (
            <details>
              <summary className="dle-citation-toggle">
                Traversed Spine Edges ({graph.edges.length})
              </summary>
              <ul className="dle-citations-list">
                {graph.edges.map((edge, idx) => (
                  <li key={`${edge.src}-${edge.dst}-${idx}`} className="dle-citation-item dle-mono">
                    {edge.src} -&gt; {edge.dst} ({edge.edgeType}, w={edge.weight.toFixed(2)})
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </section>
  );
}
