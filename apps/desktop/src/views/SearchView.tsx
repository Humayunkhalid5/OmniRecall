import { ArrowRight, Lock, Search, Sparkles, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { engine, EngineCallError } from "../api/engine";
import type { SearchFilters } from "../api/engine";
import type { SearchResponse } from "../api/types";
import { Highlighted } from "../components/Highlighted";
import { Notice } from "../components/Notice";
import { SourceTile } from "../components/SourceTile";
import { formatClock, formatLocalTime, sourceLabels } from "../lib/format";

interface Props {
  selectedId: string | null;
  onSelect: (itemId: string) => void;
  hasItems: boolean;
  modelInstalled: boolean;
  refreshKey: number;
  /** Changes when the user asks to focus the search box (/ or Ctrl/Cmd+K). */
  focusKey?: number;
  onGoToLibrary: () => void;
  onGoToSettings: () => void;
}

const relevanceText = {
  strong: "Strong match",
  moderate: "Possible match",
  weak: "Weak match",
} as const;

const matchedText = {
  both: "keywords and meaning",
  keyword: "keywords",
  semantic: "meaning",
} as const;

const SOURCE_FILTERS: { value: string; label: string; filters: SearchFilters }[] = [
  { value: "all", label: "All sources", filters: {} },
  { value: "file", label: "Files", filters: { source_types: ["file"] } },
  { value: "audio", label: "Audio notes", filters: { formats: ["audio"] } },
  { value: "text", label: "Pasted text", filters: { source_types: ["text"] } },
  { value: "clipboard", label: "Clipboard", filters: { source_types: ["clipboard"] } },
  { value: "screenshot", label: "Screenshots", filters: { source_types: ["screenshot"] } },
];

const isMac = typeof navigator !== "undefined" && /Mac/i.test(navigator.platform);

export function SearchView({
  selectedId,
  onSelect,
  hasItems,
  modelInstalled,
  refreshKey,
  focusKey = 0,
  onGoToLibrary,
  onGoToSettings,
}: Props) {
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("all");
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showWeak, setShowWeak] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const lastQuery = useRef("");
  // Only the newest request may update the view: a slow answer to an older
  // query or source filter must not replace a newer one.
  const latest = useRef(0);

  useEffect(() => {
    inputRef.current?.focus();
    if (focusKey) inputRef.current?.select();
  }, [focusKey]);

  const run = async (text: string) => {
    const trimmed = text.trim();
    lastQuery.current = trimmed;
    const request = ++latest.current;
    if (!trimmed) {
      setResponse(null);
      setError(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const filters = SOURCE_FILTERS.find((f) => f.value === source)?.filters ?? {};
      const result = await engine.search(trimmed, filters);
      if (request !== latest.current) return;
      setResponse(result);
      setShowWeak(false);
    } catch (e) {
      if (request !== latest.current) return;
      setError((e as EngineCallError).message);
      setResponse(null);
    } finally {
      if (request === latest.current) setLoading(false);
    }
  };

  // Re-run the current search after a delete or new indexing.
  useEffect(() => {
    if (lastQuery.current) void run(lastQuery.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey, source]);

  // Weak matches stay one click away when better evidence exists.
  const results = response?.results ?? [];
  const hasStronger = results.some((r) => r.relevance !== "weak");
  const visible =
    hasStronger && !showWeak ? results.filter((r) => r.relevance !== "weak") : results;
  const hidden = results.length - visible.length;

  return (
    <section className="search view" aria-label="Search">
      <div className="page-head">
        <p className="eyebrow">Your memory, searchable</p>
        <h2 className="page-title">
          Find anything you have <span className="gradient-text">seen</span>.
        </h2>
        <p className="page-sub">
          Describe it in your own words. Results come from your device only.
        </p>
      </div>
      <form
        className="search-form"
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          void run(query);
        }}
      >
        <Search size={20} aria-hidden="true" />
        <label htmlFor="query" className="sr-only">
          Search your history
        </label>
        <input
          id="query"
          ref={inputRef}
          type="search"
          placeholder="Ask in your own words, e.g. “the error I copied about a moved value”"
          value={query}
          maxLength={1000}
          onChange={(event) => setQuery(event.target.value)}
          autoComplete="off"
          spellCheck={false}
        />
        {/* Never disabled: a new search while one is running replaces it. */}
        <button type="submit" className="primary" aria-busy={loading}>
          {loading ? <span className="spinner" aria-hidden="true" /> : null}
          {loading ? "Searching…" : "Search"}
        </button>
      </form>
      <div className="search-hint">
        <div className="chips" role="group" aria-label="Source">
          {SOURCE_FILTERS.map((option) => (
            <button
              key={option.value}
              type="button"
              className="chip"
              aria-pressed={source === option.value}
              onClick={() => setSource(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <p className="muted small" aria-hidden="true">
          <span className="kbd">/</span> or <span className="kbd">{isMac ? "⌘" : "Ctrl"}</span>+
          <span className="kbd">K</span> to search from anywhere
        </p>
      </div>

      {!modelInstalled && (
        <Notice
          tone="warning"
          title="Meaning-based search is off"
          action={
            <button type="button" onClick={onGoToSettings}>
              Set up model
            </button>
          }
        >
          The local search model is not installed, so results match keywords only.
        </Notice>
      )}
      {modelInstalled && response?.semantic_unavailable_reason === "index_repairing" && (
        <Notice tone="warning" title="The search index is being repaired">
          Part of the index on this device was damaged, so OmniRecall is rebuilding it from your
          stored text. Until it finishes, results match keywords only. Nothing you saved is lost.
        </Notice>
      )}
      {error && <Notice tone="error">{error}</Notice>}

      {!response && !error && !hasItems && (
        <div className="empty">
          <span className="tile lg" aria-hidden="true">
            <Upload size={26} strokeWidth={2.2} />
          </span>
          <h2>Nothing indexed yet</h2>
          <p className="muted">Import documents or paste text, then search it by meaning.</p>
          <button type="button" className="primary" onClick={onGoToLibrary}>
            Import something <ArrowRight size={16} aria-hidden="true" />
          </button>
        </div>
      )}
      {!response && !error && hasItems && !loading && (
        <div className="empty">
          <span className="tile lg" aria-hidden="true">
            <Sparkles size={26} strokeWidth={2.2} />
          </span>
          <p className="muted">Search everything you have imported. Results stay on this device.</p>
          <ul className="tips">
            <li>
              <Sparkles size={14} aria-hidden="true" />
              Describe the idea, not the exact words: “budget we agreed on in March”.
            </li>
            <li>
              <Search size={14} aria-hidden="true" />
              Pick a source above to search only audio notes, screenshots, or files.
            </li>
            <li>
              <Lock size={14} aria-hidden="true" />
              Searches never leave this computer and are not logged.
            </li>
          </ul>
        </div>
      )}

      {response && (
        <>
          <p className="result-meta" aria-live="polite">
            {response.count === 0
              ? "No results."
              : `${visible.length} result${visible.length === 1 ? "" : "s"} in ${Math.round(response.took_ms)} ms`}
          </p>
          {response.count > 0 && response.no_strong_match && (
            <Notice tone="info">
              No strong match was found. These are the closest passages; check them before relying
              on them.
            </Notice>
          )}
          {response.count === 0 && (
            <div className="empty">
              <span className="tile lg" aria-hidden="true">
                <Search size={26} strokeWidth={2.2} />
              </span>
              <p>
                Try fewer or different words{source !== "all" ? ", or search all sources" : ""}.
              </p>
            </div>
          )}
          <ol className="results" aria-label="Search results">
            {visible.map((result) => (
              <li key={result.chunk_id}>
                <button
                  type="button"
                  className={`result ${selectedId === result.item_id ? "selected" : ""}`}
                  onClick={() => onSelect(result.item_id)}
                  aria-describedby={`why-${result.chunk_id}`}
                >
                  <SourceTile
                    kind={typeof result.start_ms === "number" ? "audio" : result.source_type}
                  />
                  <span className="result-body">
                    <span className="result-head">
                      <span className="result-title">
                        {result.source_label || sourceLabels[result.source_type]}
                      </span>
                      <span className={`badge rel-${result.relevance}`}>
                        {relevanceText[result.relevance]}
                      </span>
                    </span>
                    <span className="snippet">
                      <Highlighted text={result.snippet} ranges={result.highlights} />
                    </span>
                    <span className="result-foot" id={`why-${result.chunk_id}`}>
                      <span>
                        {typeof result.start_ms === "number"
                          ? sourceLabels.audio
                          : sourceLabels[result.source_type]}
                      </span>
                      <time dateTime={result.captured_at}>
                        {formatLocalTime(result.captured_at)}
                      </time>
                      {typeof result.start_ms === "number" && (
                        <span>at {formatClock(result.start_ms)} in the recording</span>
                      )}
                      <span>matched by {matchedText[result.matched_by]}</span>
                      {result.more_matches > 0 && <span>+{result.more_matches} more passages</span>}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ol>
          {hidden > 0 && (
            <button type="button" className="show-weak" onClick={() => setShowWeak(true)}>
              Show {hidden} weaker match{hidden === 1 ? "" : "es"}
            </button>
          )}
        </>
      )}
    </section>
  );
}
