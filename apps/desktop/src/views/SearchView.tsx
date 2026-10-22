import { useEffect, useRef, useState } from "react";
import { engine, EngineCallError } from "../api/engine";
import type { SearchFilters } from "../api/engine";
import type { SearchResponse } from "../api/types";
import { Highlighted } from "../components/Highlighted";
import { Notice } from "../components/Notice";
import { formatClock, formatLocalTime, sourceLabels } from "../lib/format";

interface Props {
  selectedId: string | null;
  onSelect: (itemId: string) => void;
  hasItems: boolean;
  modelInstalled: boolean;
  refreshKey: number;
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

export function SearchView({
  selectedId,
  onSelect,
  hasItems,
  modelInstalled,
  refreshKey,
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

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const run = async (text: string) => {
    const trimmed = text.trim();
    lastQuery.current = trimmed;
    if (!trimmed) {
      setResponse(null);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const filters = SOURCE_FILTERS.find((f) => f.value === source)?.filters ?? {};
      const result = await engine.search(trimmed, filters);
      if (lastQuery.current === trimmed) {
        setResponse(result);
        setShowWeak(false);
      }
    } catch (e) {
      setError((e as EngineCallError).message);
      setResponse(null);
    } finally {
      setLoading(false);
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
    <section className="search" aria-label="Search">
      <form
        className="search-form"
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          void run(query);
        }}
      >
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
        />
        <label htmlFor="source-filter" className="sr-only">
          Source
        </label>
        <select
          id="source-filter"
          value={source}
          onChange={(event) => setSource(event.target.value)}
        >
          {SOURCE_FILTERS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <button type="submit" className="primary" disabled={loading}>
          {loading ? "Searching…" : "Search"}
        </button>
      </form>

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
      {error && <Notice tone="error">{error}</Notice>}

      {!response && !error && !hasItems && (
        <div className="empty">
          <h2>Nothing indexed yet</h2>
          <p>Import documents or paste text, then search it by meaning.</p>
          <button type="button" className="primary" onClick={onGoToLibrary}>
            Import something
          </button>
        </div>
      )}
      {!response && !error && hasItems && !loading && (
        <div className="empty">
          <p className="muted">Search everything you have imported. Results stay on this device.</p>
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
                    <span>{sourceLabels[result.source_type]}</span>
                    <time dateTime={result.captured_at}>{formatLocalTime(result.captured_at)}</time>
                    {typeof result.start_ms === "number" && (
                      <span>at {formatClock(result.start_ms)} in the recording</span>
                    )}
                    <span>matched by {matchedText[result.matched_by]}</span>
                    {result.more_matches > 0 && <span>+{result.more_matches} more passages</span>}
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
