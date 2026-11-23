import type { ReleaseMode } from "../types/dle";
import "./components.css";

interface ReleaseBadgeProps {
  mode: ReleaseMode;
}

const LABELS: Record<ReleaseMode, string> = {
  released: "Verified",
  released_advisory: "Advisory",
  held: "Held for review",
  tool_call: "Tool call",
  passthrough: "Pass-through",
  error: "Error",
};

function ModeIcon({ mode }: { mode: ReleaseMode }) {
  switch (mode) {
    case "released":
      return (
        <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" fill="currentColor">
          <path d="M13.78 4.22a.75.75 0 0 1 0 1.06l-7.25 7.25a.75.75 0 0 1-1.06 0L2.22 9.28a.75.75 0 1 1 1.06-1.06L6 10.94l6.72-6.72a.75.75 0 0 1 1.06 0Z" />
        </svg>
      );
    case "released_advisory":
      return (
        <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" fill="currentColor">
          <path d="M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13Zm0 3a.75.75 0 0 1 .75.75v.01a.75.75 0 0 1-1.5 0V5.25A.75.75 0 0 1 8 4.5Zm0 2.5a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5A.75.75 0 0 1 8 7Z" />
        </svg>
      );
    case "held":
      return (
        <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" fill="currentColor">
          <path d="M5.5 3.5A1 1 0 0 1 6.5 4.5v7a1 1 0 1 1-2 0v-7a1 1 0 0 1 1-1Zm5 0a1 1 0 0 1 1 1v7a1 1 0 1 1-2 0v-7a1 1 0 0 1 1-1Z" />
        </svg>
      );
    case "tool_call":
    case "passthrough":
      return (
        <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" fill="currentColor">
          <path d="M8.22 2.97a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 0 1 0 1.06l-4.25 4.25a.75.75 0 0 1-1.06-1.06l2.97-2.97H3a.75.75 0 0 1 0-1.5h8.19L8.22 4.03a.75.75 0 0 1 0-1.06Z" />
        </svg>
      );
    case "error":
      return (
        <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" fill="currentColor">
          <path d="M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13Zm-.75 3.25a.75.75 0 0 1 1.5 0v3.5a.75.75 0 0 1-1.5 0v-3.5Zm.75 6.5a.85.85 0 1 1 0-1.7.85.85 0 0 1 0 1.7Z" />
        </svg>
      );
  }
}

export function ReleaseBadge({ mode }: ReleaseBadgeProps) {
  return (
    <span className={`dle-badge dle-badge--${mode}`}>
      <ModeIcon mode={mode} />
      <span>{LABELS[mode]}</span>
    </span>
  );
}
