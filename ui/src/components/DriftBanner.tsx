import { useId, useState } from "react";
import "./components.css";

interface DriftBannerProps {
  driftLatch: "clear" | "tripped";
  onResetDrift?: (artifactId: string) => Promise<void> | void;
  initialStep?: "banner" | "confirm1" | "confirm2";
  initialArtifactId?: string;
}

export function DriftBanner({
  driftLatch,
  onResetDrift,
  initialStep = "banner",
  initialArtifactId = "cal-phase6-v1",
}: DriftBannerProps) {
  const [step, setStep] = useState<"banner" | "confirm1" | "confirm2">(initialStep);
  const [artifactId, setArtifactId] = useState(initialArtifactId);
  const [confirmText, setConfirmText] = useState("");
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const artifactInputId = useId();
  const confirmInputId = useId();

  if (driftLatch === "clear") {
    return null;
  }

  const handleConfirmReset = async () => {
    if (!onResetDrift || !artifactId.trim() || confirmText.trim() !== "RESET") {
      return;
    }
    setBusy(true);
    setErrorMsg(null);
    try {
      await onResetDrift(artifactId.trim());
      setStep("banner");
      setConfirmText("");
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      className="dle-drift-banner"
      role="alert"
      aria-label="Calibration drift latch alert"
    >
      <div className="dle-panel-header">
        <div className="dle-chip-flags">
          <span className="dle-badge dle-badge--error">Drift latch tripped</span>
          <strong>
            Strict releases are held until an approved calibration artifact resets the latch.
          </strong>
        </div>
        {step === "banner" && (
          <button
            type="button"
            className="dle-btn-secondary"
            onClick={() => setStep("confirm1")}
          >
            Reset Drift Latch
          </button>
        )}
      </div>

      {step === "confirm1" && (
        <div className="dle-drift-step">
          <label className="dle-field-label" htmlFor={artifactInputId}>
            <span>Step 1 of 2: Calibration Artifact ID</span>
            <input
              id={artifactInputId}
              type="text"
              className="dle-input dle-mono"
              value={artifactId}
              placeholder="e.g. cal-phase6-v1"
              onChange={(e) => setArtifactId(e.target.value)}
            />
          </label>
          <div className="dle-chip-flags">
            <button
              type="button"
              className="dle-btn-primary"
              disabled={!artifactId.trim()}
              onClick={() => setStep("confirm2")}
            >
              Continue to Step 2
            </button>
            <button
              type="button"
              className="dle-btn-secondary"
              onClick={() => setStep("banner")}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {step === "confirm2" && (
        <div className="dle-drift-step">
          <label className="dle-field-label" htmlFor={confirmInputId}>
            <span>
              Step 2 of 2: Type RESET to clear drift latch for{" "}
              <code className="dle-mono">{artifactId}</code>
            </span>
            <input
              id={confirmInputId}
              type="text"
              className="dle-input dle-mono"
              value={confirmText}
              placeholder="RESET"
              onChange={(e) => setConfirmText(e.target.value)}
            />
          </label>
          <div className="dle-chip-flags">
            <button
              type="button"
              className="dle-btn-primary"
              disabled={busy || !artifactId.trim() || confirmText.trim() !== "RESET"}
              onClick={() => void handleConfirmReset()}
            >
              {busy ? "Resetting..." : "Confirm Drift Reset"}
            </button>
            <button
              type="button"
              className="dle-btn-secondary"
              onClick={() => {
                setStep("banner");
                setConfirmText("");
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {errorMsg && (
        <p role="alert" className="dle-banner dle-banner--error">
          {errorMsg}
        </p>
      )}
    </section>
  );
}
