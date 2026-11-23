import { useState } from "react";
import type { CitationItem } from "../types/dle";
import "./components.css";

interface CitationListProps {
  citations: CitationItem[];
}

export function CitationList({ citations }: CitationListProps) {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);

  if (citations.length === 0) {
    return (
      <section className="dle-citations" aria-label="Evidence citations">
        <h3 className="dle-citations-heading">Evidence Citations</h3>
        <p className="dle-muted">No citations returned for this response.</p>
      </section>
    );
  }

  return (
    <section className="dle-citations" aria-label="Evidence citations">
      <h3 className="dle-citations-heading">Evidence Citations ({citations.length})</h3>
      <ul className="dle-citations-list">
        {citations.map((item) => {
          const isOpen = expandedIndex === item.index;
          return (
            <li key={`${item.index}-${item.uri}`} className="dle-citation-item">
              <button
                type="button"
                className="dle-citation-toggle"
                aria-expanded={isOpen}
                onClick={() => setExpandedIndex(isOpen ? null : item.index)}
              >
                <span>
                  [{item.index}] {item.title}
                </span>
                <span>{isOpen ? "Hide source" : "Inspect source"}</span>
              </button>
              {isOpen && (
                <div className="dle-citation-detail">
                  <span className="dle-mono">{item.uri}</span>
                  {item.authorityClass && (
                    <span>Authority: {item.authorityClass}</span>
                  )}
                  {item.excerpt && (
                    <blockquote className="dle-citation-excerpt">{item.excerpt}</blockquote>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
