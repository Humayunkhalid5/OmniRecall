import { useCallback, useEffect, useRef, useState } from "react";
import { engine, onImportResult, type EngineNotification } from "./api/engine";
import type { EngineState, ImportSummary } from "./api/types";
import { Notice } from "./components/Notice";
import { useEngineEvents, useEngineState, useStatus } from "./hooks/useEngine";
import { ItemDetail } from "./views/ItemDetail";
import { LibraryView } from "./views/LibraryView";
import { SearchView } from "./views/SearchView";
import { SettingsView } from "./views/SettingsView";

type Tab = "search" | "library" | "settings";

const TABS: { id: Tab; label: string }[] = [
  { id: "search", label: "Search" },
  { id: "library", label: "Library" },
  { id: "settings", label: "Settings" },
];

const stateText: Record<EngineState["state"], string> = {
  starting: "Starting",
  running: "Ready",
  restarting: "Restarting",
  failed: "Stopped",
  stopped: "Stopped",
};

const failureText: Record<string, string> = {
  spawn_failed: "The search engine could not be started.",
  handshake_failed: "The search engine did not respond to its start-up check.",
  protocol_mismatch: "The search engine is a different version from the app.",
  crash_loop: "The search engine stopped repeatedly and was not restarted again.",
  shell_unavailable: "The app could not reach its background service.",
};

export function App() {
  const engineState = useEngineState();
  const running = engineState.state === "running";
  const { status, refresh } = useStatus(running);
  const [tab, setTab] = useState<Tab>("search");
  const [selected, setSelected] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [lastImport, setLastImport] = useState<ImportSummary | null>(null);
  const [dropError, setDropError] = useState<string | null>(null);
  const bumpTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // Coalesce bursts of indexing notifications into one refresh.
  const bump = useCallback(() => {
    if (bumpTimer.current) return;
    bumpTimer.current = setTimeout(() => {
      bumpTimer.current = undefined;
      setRefreshKey((k) => k + 1);
      refresh();
    }, 400);
  }, [refresh]);

  useEffect(() => () => clearTimeout(bumpTimer.current), []);

  useEngineEvents(
    useCallback(
      (note: EngineNotification) => {
        if (note.method.startsWith("items.") && note.method !== "items.progress") bump();
      },
      [bump],
    ),
  );

  const imported = useCallback(
    (summary: ImportSummary) => {
      setLastImport(summary);
      setDropError(null);
      bump();
    },
    [bump],
  );

  useEffect(() => {
    const unlisten = onImportResult((result) => {
      setTab("library");
      if (result.ok && result.summary) imported(result.summary);
      else setDropError(result.error?.message ?? "The dropped items could not be imported.");
    });
    return () => {
      void unlisten.then((off) => off());
    };
  }, [imported]);

  const deleted = (itemId: string) => {
    if (selected === itemId) setSelected(null);
    bump();
  };

  if (!running) return <EngineUnavailable state={engineState} />;

  const counts = status?.items ?? {};
  const hasItems = Object.entries(counts).some(([s, n]) => s !== "deleted" && (n ?? 0) > 0);
  const busy = (status?.queue.active ?? 0) + (status?.index.pending_vector_writes ?? 0) > 0;

  return (
    <div className="app">
      <header className="app-header">
        <h1>OmniRecall</h1>
        <nav aria-label="Main">
          <ul className="tabs">
            {TABS.map((t) => (
              <li key={t.id}>
                <button
                  type="button"
                  aria-current={tab === t.id ? "page" : undefined}
                  onClick={() => setTab(t.id)}
                >
                  {t.label}
                </button>
              </li>
            ))}
          </ul>
        </nav>
        <p className="engine-badge" role="status">
          <span className={`dot ${busy ? "dot-busy" : "dot-ok"}`} aria-hidden="true" />
          {busy ? `Indexing (${status?.queue.active ?? 0} queued)` : stateText[engineState.state]}
        </p>
      </header>
      <div className={`app-body ${selected ? "with-detail" : ""}`}>
        <main>
          {dropError && (
            <Notice tone="error" title="Import failed">
              {dropError}
            </Notice>
          )}
          {tab === "search" && (
            <SearchView
              selectedId={selected}
              onSelect={setSelected}
              hasItems={hasItems}
              modelInstalled={status?.model.installed ?? true}
              refreshKey={refreshKey}
              onGoToLibrary={() => setTab("library")}
              onGoToSettings={() => setTab("settings")}
            />
          )}
          {tab === "library" && (
            <LibraryView
              selectedId={selected}
              onSelect={setSelected}
              refreshKey={refreshKey}
              lastImport={lastImport}
              onImported={imported}
              onChanged={bump}
            />
          )}
          {tab === "settings" && <SettingsView status={status} onChanged={bump} />}
        </main>
        {selected && (
          <ItemDetail
            key={selected}
            itemId={selected}
            onClose={() => setSelected(null)}
            onDeleted={deleted}
          />
        )}
      </div>
    </div>
  );
}

function EngineUnavailable({ state }: { state: EngineState }) {
  const [restarting, setRestarting] = useState(false);
  const pending = state.state === "starting" || state.state === "restarting";
  if (pending) {
    return (
      <main className="center" aria-busy="true">
        <h1>OmniRecall</h1>
        <p role="status">
          {state.state === "restarting"
            ? `Restarting the search engine (attempt ${state.attempt})…`
            : "Starting the search engine…"}
        </p>
      </main>
    );
  }
  const code = state.state === "failed" ? state.code : "stopped";
  return (
    <main className="center">
      <h1>OmniRecall</h1>
      <Notice
        tone="error"
        title="The search engine is not running"
        action={
          <button
            type="button"
            className="primary"
            disabled={restarting}
            onClick={() => {
              setRestarting(true);
              engine.restart().finally(() => setRestarting(false));
            }}
          >
            {restarting ? "Restarting…" : "Restart engine"}
          </button>
        }
      >
        <p>{failureText[code] ?? "The search engine stopped."}</p>
        <p className="muted small">Diagnostic code: {code}. Your data has not been changed.</p>
      </Notice>
    </main>
  );
}
