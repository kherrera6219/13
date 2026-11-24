import { useCallback, useEffect, useId, useState } from "react";
import "./App.css";
import { AddressGraphDrawer } from "./components/AddressGraphDrawer";
import { ChatComposer, type ComposerSubmitPayload } from "./components/ChatComposer";
import { ClaimsTable } from "./components/ClaimsTable";
import { CostByTierChart } from "./components/CostByTierChart";
import { DriftBanner } from "./components/DriftBanner";
import { ExportDialog } from "./components/ExportDialog";
import { FunctionFlagsEditor } from "./components/FunctionFlagsEditor";
import { HealthPanel } from "./components/HealthPanel";
import { MessageBubble } from "./components/MessageBubble";
import { PersonaChips } from "./components/PersonaChips";
import { PersonaDrawer } from "./components/PersonaDrawer";
import { ReceiptViewer } from "./components/ReceiptViewer";
import { RunSummaryCard } from "./components/RunSummaryCard";
import { SourceRegistryTable } from "./components/SourceRegistryTable";
import { StepTimeline } from "./components/StepTimeline";
import {
  exportReceiptsBundle,
  fetchCostByTier,
  fetchFunctionFlags,
  fetchHealth,
  fetchSources,
  formatFriendlyError,
  registerSource,
  resetDriftLatch,
  sendChatMessage,
  updateFunctionFlags,
  type RegisterSourceInput,
} from "./lib/dleClient";
import type {
  ChatRun,
  ConsequentialFunctionItem,
  CostByTierDay,
  DleHeaders,
  EvidenceSource,
  HealthStatus,
} from "./types/dle";

const SESSION_KEY_STORAGE = "dle_client_key";
const SESSION_ADMIN_STORAGE = "dle_admin_key";

export function App() {
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [activeTab, setActiveTab] = useState<"chat" | "sources" | "ops">("chat");
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
  const [selectedPersonaAxis, setSelectedPersonaAxis] = useState<number | null>(null);
  const [sending, setSending] = useState(false);
  const [latestHeaders, setLatestHeaders] = useState<DleHeaders | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  const [sources, setSources] = useState<EvidenceSource[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [sourcesError, setSourcesError] = useState<string | null>(null);
  const [sourcesStatus, setSourcesStatus] = useState<string | null>(null);

  const [flags, setFlags] = useState<ConsequentialFunctionItem[]>([]);
  const [flagsSchemaVersion, setFlagsSchemaVersion] = useState("1.0.0");
  const [flagsLoading, setFlagsLoading] = useState(false);
  const [flagsError, setFlagsError] = useState<string | null>(null);
  const [flagsStatus, setFlagsStatus] = useState<string | null>(null);
  const [costDays, setCostDays] = useState<CostByTierDay[]>([]);
  const [costLoading, setCostLoading] = useState(false);
  const [opsError, setOpsError] = useState<string | null>(null);

  const keyInputId = useId();
  const adminKeyInputId = useId();
  const sessionInputId = useId();
  const chatTabId = useId();
  const sourcesTabId = useId();
  const opsTabId = useId();
  const baseUrl = typeof window !== "undefined" ? window.location.origin : "http://127.0.0.1:8740";

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const loadHealth = useCallback(async () => {
    try {
      const res = await fetchHealth(baseUrl);
      setHealth(res);
      setHealthError(null);
    } catch (err) {
      setHealthError(formatFriendlyError(err));
    }
  }, [baseUrl]);

  useEffect(() => {
    void loadHealth();
  }, [loadHealth]);

  const loadOpsData = useCallback(async () => {
    const effectiveAdmin = adminKey.trim();
    if (!effectiveAdmin) {
      setOpsError("Open Settings and enter your Middleware Admin Key (X-DLE-Admin-Key) first.");
      return;
    }
    setFlagsLoading(true);
    setCostLoading(true);
    setOpsError(null);
    setFlagsError(null);
    try {
      const [flagsRes, costRes] = await Promise.all([
        fetchFunctionFlags(baseUrl, effectiveAdmin),
        fetchCostByTier(baseUrl, effectiveAdmin, 7),
      ]);
      setFlags(flagsRes.consequentialFunctions);
      setFlagsSchemaVersion(flagsRes.schemaVersion);
      setCostDays(costRes);
    } catch (err) {
      setOpsError(formatFriendlyError(err));
    } finally {
      setFlagsLoading(false);
      setCostLoading(false);
    }
  }, [adminKey, baseUrl]);

  useEffect(() => {
    if (activeTab === "ops" && adminKey.trim().length > 0) {
      void loadOpsData();
    }
  }, [activeTab, adminKey, loadOpsData]);

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
      setSelectedPersonaAxis(result.run.personas?.[0]?.roleAxis ?? null);
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
  const inspectedPersonas = inspectedRun?.personas ?? [];
  const activePersona =
    inspectedPersonas.find((p) => p.roleAxis === selectedPersonaAxis) ??
    inspectedPersonas[0] ??
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
          <button
            id={opsTabId}
            type="button"
            role="tab"
            className={activeTab === "ops" ? "dle-tab dle-tab--active" : "dle-tab"}
            aria-selected={activeTab === "ops"}
            onClick={() => setActiveTab("ops")}
          >
            Ops &amp; Audit
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

      {health && (
        <DriftBanner
          driftLatch={health.driftLatch}
          onResetDrift={async (artifactId) => {
            const effectiveAdmin = adminKey.trim();
            if (!effectiveAdmin) {
              throw new Error(
                "Open Settings and enter your Middleware Admin Key (X-DLE-Admin-Key) first.",
              );
            }
            await resetDriftLatch(baseUrl, effectiveAdmin, artifactId);
            await loadHealth();
          }}
        />
      )}

      {activeTab === "chat" && (
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
                    onSelectReceipt={(selected) => {
                      setSelectedRunId(selected.id);
                      setSelectedPersonaAxis(selected.personas?.[0]?.roleAxis ?? null);
                    }}
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

            <RunSummaryCard
              runSummary={inspectedRun?.runSummary ?? null}
              releaseMode={inspectedRun?.releaseMode ?? latestHeaders?.releaseMode ?? null}
              terminalU={inspectedRun?.terminalU ?? null}
            />
            <PersonaChips
              personas={inspectedPersonas}
              selectedRoleAxis={activePersona?.roleAxis ?? null}
              onSelectPersona={(axis) => setSelectedPersonaAxis(axis)}
            />
            <PersonaDrawer
              persona={activePersona}
              objections={inspectedRun?.objections ?? []}
            />
            <StepTimeline
              steps={inspectedRun?.steps ?? []}
              parkedToolName={
                inspectedRun?.releaseMode === "tool_call" ? inspectedRun.toolCallName : undefined
              }
            />
            <ClaimsTable claims={inspectedRun?.claims ?? []} />
            <AddressGraphDrawer
              coordinate={inspectedRun?.coordinate ?? null}
              graph={inspectedRun?.graph ?? null}
            />
            <ReceiptViewer receipt={inspectedRun?.receipt ?? null} />
          </aside>
        </main>
      )}
      {activeTab === "sources" && (
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
      {activeTab === "ops" && (
        <main className="dle-admin-workspace" role="tabpanel" aria-labelledby={opsTabId}>
          {opsError && (
            <div role="alert" className="dle-banner dle-banner--error">
              {opsError}
            </div>
          )}
          <div className="dle-ops-grid">
            <HealthPanel
              health={health}
              error={healthError}
              onRefresh={() => void loadHealth()}
            />
            <FunctionFlagsEditor
              flags={flags}
              loading={flagsLoading}
              error={flagsError}
              statusMessage={flagsStatus}
              onSave={async (nextFlags) => {
                const effectiveAdmin = adminKey.trim();
                if (!effectiveAdmin) {
                  setFlagsError(
                    "Open Settings and enter your Middleware Admin Key (X-DLE-Admin-Key) first.",
                  );
                  return;
                }
                setFlagsError(null);
                setFlagsStatus(null);
                try {
                  const saved = await updateFunctionFlags(baseUrl, effectiveAdmin, {
                    schemaVersion: flagsSchemaVersion,
                    consequentialFunctions: nextFlags,
                  });
                  setFlags(saved.consequentialFunctions);
                  setFlagsStatus(
                    `Saved ${saved.consequentialFunctions.length} consequential function flags.`,
                  );
                } catch (err) {
                  setFlagsError(formatFriendlyError(err));
                }
              }}
            />
            <CostByTierChart
              days={costDays}
              loading={costLoading}
              onRefresh={() => void loadOpsData()}
            />
            <ExportDialog
              onExport={async (fromIso, toIso) => {
                const effectiveAdmin = adminKey.trim();
                if (!effectiveAdmin) {
                  throw new Error(
                    "Open Settings and enter your Middleware Admin Key (X-DLE-Admin-Key) first.",
                  );
                }
                const blob = await exportReceiptsBundle(baseUrl, effectiveAdmin, fromIso, toIso);
                if (typeof window !== "undefined") {
                  const url = window.URL.createObjectURL(blob);
                  const link = document.createElement("a");
                  link.href = url;
                  link.download = "dle_receipts_bundle.zip";
                  link.click();
                  window.URL.revokeObjectURL(url);
                }
              }}
            />
          </div>
        </main>
      )}
    </div>
  );
}

export default App;
