import { useCallback, useEffect, useId, useState } from "react";
import "./App.css";
import { AddressGraphDrawer } from "./components/AddressGraphDrawer";
import { ChatComposer, type ComposerSubmitPayload } from "./components/ChatComposer";
import { ClaimsTable } from "./components/ClaimsTable";
import { MessageBubble } from "./components/MessageBubble";
import { ReceiptViewer } from "./components/ReceiptViewer";
import { SourceRegistryTable } from "./components/SourceRegistryTable";
import {
  fetchHealth,
  fetchSources,
  formatFriendlyError,
  registerSource,
  sendChatMessage,
  type RegisterSourceInput,
} from "./lib/dleClient";
import type { ChatRun, DleHeaders, EvidenceSource, HealthStatus } from "./types/dle";

const SESSION_KEY_STORAGE = "dle_client_key";
const SESSION_ADMIN_STORAGE = "dle_admin_key";

export function App() {
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [activeTab, setActiveTab] = useState<"chat" | "sources">("chat");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [apiKey, setApiKey] = useState(() => {
    if (typeof window !== "undefined") {
      return window.sessionStorage.getItem(SESSION_KEY_STORAGE) ?? "";
    }
    return "";
  });
  const [adminKey, setAdminKey] = useState(() => {
    if (typeof window !== "undefined") {
      return window.sessionStorage.getItem(SESSION_ADMIN_STORAGE) ?? "";
    }
    return "";
  });
  const [sessionOverride, setSessionOverride] = useState("");
  const [runs, setRuns] = useState<ChatRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [latestHeaders, setLatestHeaders] = useState<DleHeaders | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  const [sources, setSources] = useState<EvidenceSource[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [sourcesError, setSourcesError] = useState<string | null>(null);
  const [sourcesStatus, setSourcesStatus] = useState<string | null>(null);

  const keyInputId = useId();
  const adminKeyInputId = useId();
  const sessionInputId = useId();
  const chatTabId = useId();
  const sourcesTabId = useId();
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

  const loadSources = useCallback(async () => {
    const effectiveKey = apiKey.trim();
    if (!effectiveKey) {
      setSourcesError("Enter your Middleware Client API Key in Settings to list sources.");
      return;
    }
    setSourcesLoading(true);
    setSourcesError(null);
    try {
      const res = await fetchSources(baseUrl, effectiveKey);
      setSources(res.sources);
    } catch (err) {
      setSourcesError(formatFriendlyError(err));
    } finally {
      setSourcesLoading(false);
    }
  }, [apiKey, baseUrl]);

  useEffect(() => {
    if (activeTab === "sources" && apiKey.trim().length > 0) {
      void loadSources();
    }
  }, [activeTab, apiKey, loadSources]);

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

  const handleAdminKeyChange = (val: string) => {
    setAdminKey(val);
    if (typeof window !== "undefined") {
      if (val) {
        window.sessionStorage.setItem(SESSION_ADMIN_STORAGE, val);
      } else {
        window.sessionStorage.removeItem(SESSION_ADMIN_STORAGE);
      }
    }
  };

  const handleRegisterSource = async (input: RegisterSourceInput) => {
    const effectiveAdmin = adminKey.trim();
    if (!effectiveAdmin) {
      setSourcesError("Open Settings and enter your Middleware Admin Key (X-DLE-Admin-Key) first.");
      return;
    }
    setSourcesError(null);
    setSourcesStatus(null);
    try {
      const created = await registerSource(baseUrl, effectiveAdmin, input);
      setSourcesStatus(`Registered "${created.title}" (${created.authorityClass}).`);
      if (apiKey.trim()) {
        await loadSources();
      } else {
        setSources((prev) => [created, ...prev]);
      }
    } catch (err) {
      setSourcesError(formatFriendlyError(err));
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
      if (result.run.receiptId) {
        setSelectedRunId(result.run.id);
      }
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

  const assistantRuns = runs.filter((r) => r.role === "assistant");
  const inspectedRun =
    assistantRuns.find((r) => r.id === selectedRunId) ??
    [...assistantRuns].reverse().find((r) => r.receiptId !== null) ??
    assistantRuns[assistantRuns.length - 1] ??
    null;

  const healthClass = healthError
    ? "dle-health-pill dle-health-pill--error"
    : health?.status === "ok"
      ? "dle-health-pill dle-health-pill--ok"
      : "dle-health-pill dle-health-pill--degraded";

  const healthText = healthError
    ? "Health: unreachable"
    : health
      ? `Health: ${health.status} (${health.kernelFunctions} kernels · NLI ${health.nliLoaded ? "on" : "off"})`
      : "Health: checking";

  return (
    <div className="dle-shell">
      <header className="dle-topbar">
        <div className="dle-brand">
          <h1 className="dle-brand-title">DataLogicEngine</h1>
          <span className="dle-brand-sub">13-Axis DVSS Control Plane</span>
        </div>

        <nav className="dle-tablist" role="tablist" aria-label="Workspace views">
          <button
            id={chatTabId}
            type="button"
            role="tab"
            className={activeTab === "chat" ? "dle-tab dle-tab--active" : "dle-tab"}
            aria-selected={activeTab === "chat"}
            onClick={() => setActiveTab("chat")}
          >
            Chat &amp; Inspector
          </button>
          <button
            id={sourcesTabId}
            type="button"
            role="tab"
            className={activeTab === "sources" ? "dle-tab dle-tab--active" : "dle-tab"}
            aria-selected={activeTab === "sources"}
            onClick={() => setActiveTab("sources")}
          >
            Sources Admin
          </button>
        </nav>

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
            <label className="dle-settings-field" htmlFor={adminKeyInputId}>
              <span>Middleware Admin Key (loopback)</span>
              <input
                id={adminKeyInputId}
                type="password"
                className="dle-input dle-mono"
                value={adminKey}
                placeholder="Enter X-DLE-Admin-Key"
                onChange={(e) => handleAdminKeyChange(e.target.value)}
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

      {activeTab === "chat" ? (
        <main className="dle-workspace" role="tabpanel" aria-labelledby={chatTabId}>
          <div className="dle-chat-column">
            <section className="dle-transcript" aria-label="Conversation">
              {runs.length === 0 ? (
                <div className="dle-empty-state">
                  <h2>Ready for governed or pass-through inference</h2>
                  <p>
                    Open Settings to supply your middleware client API key, register sources under
                    Sources Admin if using governed strict mode, and send a prompt.
                  </p>
                </div>
              ) : (
                runs.map((run) => (
                  <MessageBubble
                    key={run.id}
                    run={run}
                    selected={inspectedRun?.id === run.id}
                    onSelectReceipt={(selected) => setSelectedRunId(selected.id)}
                  />
                ))
              )}
            </section>

            <ChatComposer sending={sending} onSubmit={handleSubmit} />
          </div>

          <aside className="dle-inspector" aria-label="Run Inspector">
            <h2>Run Inspector</h2>
            <dl className="dle-dl">
              <dt>Release Mode</dt>
              <dd className="dle-mono">{inspectedRun?.releaseMode ?? latestHeaders?.releaseMode ?? "—"}</dd>
              <dt>Receipt ID</dt>
              <dd className="dle-mono">{inspectedRun?.receiptId ?? latestHeaders?.receiptId ?? "—"}</dd>
              <dt>Tier</dt>
              <dd className="dle-mono">{inspectedRun?.tier ?? latestHeaders?.tier ?? "—"}</dd>
              <dt>API Version</dt>
              <dd className="dle-mono">{latestHeaders?.apiVersion ?? "—"}</dd>
              <dt>NLI Loaded</dt>
              <dd className="dle-mono">{health ? (health.nliLoaded ? "yes" : "no") : "—"}</dd>
              <dt>Drift Latch</dt>
              <dd className="dle-mono">{health?.driftLatch ?? "—"}</dd>
            </dl>

            <ClaimsTable claims={inspectedRun?.claims ?? []} />
            <AddressGraphDrawer
              coordinate={inspectedRun?.coordinate ?? null}
              graph={inspectedRun?.graph ?? null}
            />
            <ReceiptViewer receipt={inspectedRun?.receipt ?? null} />
          </aside>
        </main>
      ) : (
        <main className="dle-admin-workspace" role="tabpanel" aria-labelledby={sourcesTabId}>
          {sourcesError && (
            <div role="alert" className="dle-banner dle-banner--error">
              {sourcesError}
            </div>
          )}
          {sourcesStatus && (
            <div role="status" className="dle-banner dle-banner--ok">
              {sourcesStatus}
            </div>
          )}
          <SourceRegistryTable
            sources={sources}
            loading={sourcesLoading}
            onRefresh={() => void loadSources()}
            onRegister={handleRegisterSource}
          />
        </main>
      )}
    </div>
  );
}

export default App;
