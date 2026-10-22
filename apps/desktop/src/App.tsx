import { Library, Search, Settings, type LucideIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { engine, onImportResult, type EngineNotification } from "./api/engine";
import type { EngineState, ImportSummary } from "./api/types";
import { BrandMark } from "./components/BrandMark";
import { CaptureIndicator } from "./components/CaptureIndicator";
import { Notice } from "./components/Notice";
import { useCapture } from "./hooks/useCapture";
import { useEngineEvents, useEngineState, useStatus } from "./hooks/useEngine";
import { DatabaseRecovery } from "./views/DatabaseRecovery";
import { FirstRun } from "./views/FirstRun";
import { ItemDetail } from "./views/ItemDetail";
import { LibraryView } from "./views/LibraryView";
import { SearchView } from "./views/SearchView";
import { SettingsView } from "./views/SettingsView";

type Tab = "search" | "library" | "settings";

const TABS: { id: Tab; label: string; icon: LucideIcon }[] = [
  { id: "search", label: "Search", icon: Search },
  { id: "library", label: "Library", icon: Library },
  { id: "settings", label: "Settings", icon: Settings },
];

/** True while a modal dialog is open; its own Escape handling comes first. */
function dialogOpen(): boolean {
  return document.querySelector("dialog[open]") !== null;
}

function typingIn(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

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
  const { status, recovery, refresh } = useStatus(running);
  const capture = useCapture(running);
  const [firstRun, setFirstRun] = useState<boolean | null>(null);
  const [tab, setTab] = useState<Tab>("search");
  const [selected, setSelected] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [lastImport, setLastImport] = useState<ImportSummary | null>(null);
  const [dropError, setDropError] = useState<string | null>(null);
  const [searchFocus, setSearchFocus] = useState(0);
  const bumpTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // "/" or Ctrl/Cmd+K jumps to the search box; Escape closes the detail panel.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || dialogOpen()) return;
      const searchKey =
        (event.key.toLowerCase() === "k" && (event.ctrlKey || event.metaKey) && !event.altKey) ||
        (event.key === "/" && !typingIn(event.target));
      if (searchKey) {
        event.preventDefault();
        setTab("search");
        setSearchFocus((n) => n + 1);
      } else if (event.key === "Escape" && !typingIn(event.target)) {
        setSelected(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

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
        if (note.method === "media.pruned" || note.method === "index.repaired") bump();
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

  useEffect(() => {
    if (!running) return;
    engine
      .getSettings()
      .then((r) => setFirstRun(!r.settings.first_run_completed))
      .catch(() => setFirstRun(false));
  }, [running]);

  const deleted = (itemId: string) => {
    if (selected === itemId) setSelected(null);
    bump();
  };

  if (!running) return <EngineUnavailable state={engineState} />;
  if (recovery) return <DatabaseRecovery recovery={recovery} />;
  if (firstRun) return <FirstRun onDone={() => setFirstRun(false)} />;

  const counts = status?.items ?? {};
  const hasItems = Object.entries(counts).some(([s, n]) => s !== "deleted" && (n ?? 0) > 0);
  const busy = (status?.queue.active ?? 0) + (status?.index.pending_vector_writes ?? 0) > 0;

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <BrandMark />
          <h1>
            OmniRecall <span className="beta-badge">Beta</span>
          </h1>
        </div>
        <nav aria-label="Main">
          <ul className="tabs">
            {TABS.map((t) => (
              <li key={t.id}>
                <button
                  type="button"
                  aria-current={tab === t.id ? "page" : undefined}
                  onClick={() => setTab(t.id)}
                >
                  <t.icon size={18} aria-hidden="true" />
                  {t.label}
                </button>
              </li>
            ))}
          </ul>
        </nav>
        <div className="sidebar-foot">
          <CaptureIndicator
            capture={capture.capture}
            onToggle={() => void capture.toggle()}
            onOpenSettings={() => setTab("settings")}
          />
          <p className="engine-badge" role="status">
            <span className={`dot ${busy ? "dot-busy" : "dot-ok"}`} aria-hidden="true" />
            {busy
              ? status?.queue.backlog
                ? `Indexing (${status.queue.backlog} waiting)`
                : "Indexing…"
              : `${stateText[engineState.state]} · on this device`}
          </p>
        </div>
      </header>
      <div className={`app-body ${selected ? "with-detail" : ""}`}>
        <main>
          {dropError && (
            <Notice tone="error" title="Import failed" onDismiss={() => setDropError(null)}>
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
              focusKey={searchFocus}
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
              onDismissImport={() => setLastImport(null)}
              onImported={imported}
              onChanged={bump}
            />
          )}
          {tab === "settings" && (
            <SettingsView
              status={status}
              capture={capture}
              refreshKey={refreshKey}
              onChanged={bump}
            />
          )}
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
  const brand = (
    <div className="center-brand">
      <BrandMark size={44} />
      <h1>OmniRecall</h1>
    </div>
  );
  if (pending) {
    return (
      <main className="center" aria-busy="true">
        {brand}
        <p className="loading-line" role="status">
          <span className="spinner" aria-hidden="true" />
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
      {brand}
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
              // A failed restart is reported through the next engine state.
              engine
                .restart()
                .catch(() => undefined)
                .finally(() => setRestarting(false));
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
