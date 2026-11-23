import { useEffect, useId, useState } from "react";
import "./App.css";
import { ChatComposer, type ComposerSubmitPayload } from "./components/ChatComposer";
import { MessageBubble } from "./components/MessageBubble";
import { fetchHealth, formatFriendlyError, sendChatMessage } from "./lib/dleClient";
import type { ChatRun, DleHeaders, HealthStatus } from "./types/dle";

const SESSION_KEY_STORAGE = "dle_client_key";

export function App() {
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [apiKey, setApiKey] = useState(() => {
    if (typeof window !== "undefined") {
      return window.sessionStorage.getItem(SESSION_KEY_STORAGE) ?? "";
    }
    return "";
  });
  const [sessionOverride, setSessionOverride] = useState("");
  const [runs, setRuns] = useState<ChatRun[]>([]);
  const [sending, setSending] = useState(false);
  const [latestHeaders, setLatestHeaders] = useState<DleHeaders | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  const keyInputId = useId();
  const sessionInputId = useId();
  const baseUrl = typeof window !== "undefined" ? window.location.origin : "http://127.0.0.1:8740";

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    let active = true;
    const loadHealth = async () => {
      try {
        const res = await fetchHealth(baseUrl);
        if (active) {
          setHealth(res);
          setHealthError(null);
        }
      } catch (err) {
        if (active) {
          setHealthError(formatFriendlyError(err));
        }
      }
    };
    void loadHealth();
    return () => {
      active = false;
    };
  }, [baseUrl]);

  const handleKeyChange = (val: string) => {
    setApiKey(val);
    if (typeof window !== "undefined") {
      if (val) {
        window.sessionStorage.setItem(SESSION_KEY_STORAGE, val);
      } else {
        window.sessionStorage.removeItem(SESSION_KEY_STORAGE);
      }
    }
  };

  const handleSubmit = async (payload: ComposerSubmitPayload) => {
    const userRun: ChatRun = {
      id: `user-${Date.now()}`,
      role: "user",
      model: payload.model,
      text: payload.prompt,
      releaseMode: "passthrough",
      noticeText: "",
      receiptId: null,
      tier: null,
      timestamp: new Date().toISOString(),
    };

    const nextHistory = [...runs, userRun];
    const streamId = `stream-${Date.now()}`;
    setSending(true);
    setRuns(
      payload.streaming
        ? [
            ...nextHistory,
            {
              id: streamId,
              role: "assistant",
              model: payload.model,
              text: "Waiting for response...",
              releaseMode: "released",
              noticeText: "Streaming response in progress; keepalives active.",
              receiptId: null,
              tier: null,
              streaming: true,
              timestamp: new Date().toISOString(),
            },
          ]
        : nextHistory,
    );

    try {
      const effectiveKey = apiKey.trim();
      if (!effectiveKey) {
        throw new Error("401 UNAUTHENTICATED");
      }
      const result = await sendChatMessage({
        baseUrl,
        apiKey: effectiveKey,
        model: payload.model,
        prompt: payload.prompt,
        history: runs,
        streaming: payload.streaming,
        sessionOverride,
        onChunk: (partial) => {
          setRuns((prev) =>
            prev.map((item) => (item.id === streamId ? { ...item, text: partial } : item)),
          );
        },
      });
      setLatestHeaders(result.headers);
      setRuns([...nextHistory, result.run]);
    } catch (err) {
      const friendly = formatFriendlyError(err);
      const errRun: ChatRun = {
        id: `error-${Date.now()}`,
        role: "assistant",
        model: payload.model,
        text: friendly,
        releaseMode: "error",
        noticeText: friendly,
        receiptId: null,
        tier: null,
        errorDetail: friendly,
        timestamp: new Date().toISOString(),
      };
      setRuns([...nextHistory, errRun]);
    } finally {
      setSending(false);
    }
  };

  const healthClass = healthError
    ? "dle-health-pill dle-health-pill--error"
    : health?.status === "ok"
      ? "dle-health-pill dle-health-pill--ok"
      : "dle-health-pill dle-health-pill--degraded";

  const healthText = healthError
    ? "Health: unreachable"
    : health
      ? `Health: ${health.status} (${health.kernelFunctions} kernels)`
      : "Health: checking";

  return (
    <div className="dle-shell">
      <header className="dle-topbar">
        <div className="dle-brand">
          <h1 className="dle-brand-title">DataLogicEngine</h1>
          <span className="dle-brand-sub">13-Axis DVSS Control Plane</span>
        </div>

        <div className="dle-toolbar">
          <span className={healthClass} aria-live="polite">
            {healthText}
          </span>
          <button
            type="button"
            className="dle-btn-secondary"
            onClick={() => setTheme((prev) => (prev === "light" ? "dark" : "light"))}
          >
            {theme === "light" ? "Dark theme" : "Light theme"}
          </button>
          <button
            type="button"
            className="dle-btn-secondary"
            aria-expanded={settingsOpen}
            onClick={() => setSettingsOpen((prev) => !prev)}
          >
            Settings
          </button>
        </div>
      </header>

      {settingsOpen && (
        <section className="dle-settings-drawer" aria-label="Middleware connection settings">
          <div className="dle-settings-grid">
            <label className="dle-settings-field" htmlFor={keyInputId}>
              <span>Middleware Client API Key</span>
              <input
                id={keyInputId}
                type="password"
                className="dle-input dle-mono"
                value={apiKey}
                placeholder="Enter X-Goog-Api-Key"
                onChange={(e) => handleKeyChange(e.target.value)}
              />
            </label>
            <label className="dle-settings-field" htmlFor={sessionInputId}>
              <span>Optional X-DLE-Session Override</span>
              <input
                id={sessionInputId}
                type="text"
                className="dle-input dle-mono"
                value={sessionOverride}
                placeholder="Auto history hash"
                onChange={(e) => setSessionOverride(e.target.value)}
              />
            </label>
          </div>
        </section>
      )}

      <main className="dle-workspace">
        <div className="dle-chat-column">
          <section className="dle-transcript" aria-label="Conversation">
            {runs.length === 0 ? (
              <div className="dle-empty-state">
                <h2>Ready for governed or pass-through inference</h2>
                <p>
                  Open Settings to supply your middleware client API key, choose a model, and send
                  a prompt.
                </p>
              </div>
            ) : (
              runs.map((run) => <MessageBubble key={run.id} run={run} />)
            )}
          </section>

          <ChatComposer sending={sending} onSubmit={handleSubmit} />
        </div>

        <aside className="dle-inspector" aria-label="Latest response headers">
          <h2>Response Inspector</h2>
          <dl className="dle-dl">
            <dt>Release Mode</dt>
            <dd className="dle-mono">{latestHeaders?.releaseMode ?? "—"}</dd>
            <dt>Receipt ID</dt>
            <dd className="dle-mono">{latestHeaders?.receiptId ?? "—"}</dd>
            <dt>Tier</dt>
            <dd className="dle-mono">{latestHeaders?.tier ?? "—"}</dd>
            <dt>API Version</dt>
            <dd className="dle-mono">{latestHeaders?.apiVersion ?? "—"}</dd>
            <dt>Drift Latch</dt>
            <dd className="dle-mono">{health?.driftLatch ?? "—"}</dd>
          </dl>
        </aside>
      </main>
    </div>
  );
}
