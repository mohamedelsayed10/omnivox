import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type ReactNode } from "react";
import {
  AlertCircle,
  CheckCircle2,
  FileText,
  Library,
  Loader2,
  RefreshCw,
  Search,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import { api } from "../api/client";
import type { KnowledgeDocument, SearchResult } from "../api/types";
import { ErrorBanner, toUiError, type UiError } from "../components/ErrorBanner";
import { formatBytes } from "../lib/format";
import { useSettings } from "../state/settings";
import { useToast } from "../state/toast";

const ACCEPT = [".txt", ".md", ".pdf"];
const isSupported = (name: string) => ACCEPT.some((ext) => name.toLowerCase().endsWith(ext));

interface UploadItem {
  id: number;
  name: string;
  size: number;
  status: "uploading" | "done" | "error";
  chunks?: number;
  characters?: number;
  source?: string;
  error?: UiError;
}

export function KnowledgeView() {
  return (
    <section className="view view-scroll kb" aria-label="Knowledge base">
      <div className="kb-grid">
        <div className="kb-col">
          <UploadCard />
          <DocumentsCard />
        </div>
        <div className="kb-col">
          <SearchCard />
        </div>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ shared store

/** Document list shared by the upload and list cards via a tiny event. */
const REFRESH_EVENT = "omnivox:kb-refresh";
const requestRefresh = () => window.dispatchEvent(new Event(REFRESH_EVENT));

// ------------------------------------------------------------------ upload

function UploadCard() {
  const toast = useToast();
  const [items, setItems] = useState<UploadItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const [sourceName, setSourceName] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const nextId = useRef(1);
  const depth = useRef(0);

  const upload = useCallback(
    async (files: File[]) => {
      if (!files.length) return;
      const single = files.length === 1;
      const override = single ? sourceName.trim() : "";
      for (const file of files) {
        const id = nextId.current++;
        const base: UploadItem = { id, name: file.name, size: file.size, status: "uploading" };
        if (!isSupported(file.name)) {
          setItems((l) => [
            {
              ...base,
              status: "error",
              error: { message: `Unsupported file type. Use ${ACCEPT.join(", ")}.`, code: "unsupported_type" },
            },
            ...l,
          ]);
          continue;
        }
        setItems((l) => [base, ...l]);
        try {
          const r = await api.uploadDocument(file, override || undefined);
          setItems((l) =>
            l.map((it) =>
              it.id === id ? { ...it, status: "done", chunks: r.chunks, characters: r.characters, source: r.source } : it,
            ),
          );
          toast.success(`Indexed ${r.source}: ${r.chunks} chunk${r.chunks === 1 ? "" : "s"}`);
          requestRefresh();
        } catch (e) {
          setItems((l) => l.map((it) => (it.id === id ? { ...it, status: "error", error: toUiError(e) } : it)));
        }
      }
      if (single) setSourceName("");
    },
    [sourceName, toast],
  );

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    depth.current = 0;
    setDragging(false);
    void upload(Array.from(e.dataTransfer.files));
  };

  return (
    <div className="card kb-card">
      <div className="kb-card-head">
        <h2>Add documents</h2>
        <span className="muted">txt · md · pdf</span>
      </div>

      <div
        className={`dropzone${dragging ? " over" : ""}`}
        role="button"
        tabIndex={0}
        aria-label="Upload documents: drop files here or press Enter to browse"
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragEnter={(e) => {
          e.preventDefault();
          depth.current++;
          setDragging(true);
        }}
        onDragOver={(e) => e.preventDefault()}
        onDragLeave={() => {
          depth.current = Math.max(0, depth.current - 1);
          if (depth.current === 0) setDragging(false);
        }}
        onDrop={onDrop}
      >
        <div className="drop-icon" aria-hidden>
          <UploadCloud size={26} />
        </div>
        <strong>{dragging ? "Release to upload" : "Drag & drop files here"}</strong>
        <span>
          or <u>browse</u> from your computer
        </span>
        <input
          ref={inputRef}
          type="file"
          multiple
          hidden
          accept={ACCEPT.join(",")}
          onChange={(e) => {
            void upload(Array.from(e.target.files ?? []));
            e.target.value = "";
          }}
        />
      </div>

      <div className="source-field">
        <label className="field-label" htmlFor="kb-source">
          Source name <span className="muted">(optional, single file uploads)</span>
        </label>
        <input
          id="kb-source"
          className="input"
          placeholder="Defaults to the file name"
          value={sourceName}
          onChange={(e) => setSourceName(e.target.value)}
        />
      </div>

      {items.length > 0 && (
        <ul className="uploads" aria-label="Uploads">
          {items.slice(0, 6).map((it) => (
            <li key={it.id} className={`upload ${it.status}`}>
              <span className="upload-icon" aria-hidden>
                {it.status === "uploading" ? (
                  <Loader2 size={16} className="spin" />
                ) : it.status === "done" ? (
                  <CheckCircle2 size={16} color="var(--ok)" />
                ) : (
                  <AlertCircle size={16} color="var(--err)" />
                )}
              </span>
              <div className="upload-main">
                <div className="upload-name">
                  <span className="truncate">{it.source ?? it.name}</span>
                  <span className="muted mono">{formatBytes(it.size)}</span>
                </div>
                {it.status === "uploading" && <div className="progress" aria-label="Uploading" />}
                {it.status === "done" && (
                  <div className="muted">
                    {it.chunks} chunk{it.chunks === 1 ? "" : "s"} · {it.characters?.toLocaleString()} characters
                  </div>
                )}
                {it.error && <ErrorBanner error={it.error} />}
              </div>
              {it.status !== "uploading" && (
                <button
                  className="btn btn-ghost btn-icon btn-sm"
                  aria-label={`Dismiss ${it.name}`}
                  onClick={() => setItems((l) => l.filter((x) => x.id !== it.id))}
                >
                  <X size={14} />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ documents

function DocumentsCard() {
  const toast = useToast();
  const { keyVersion } = useSettings();
  const [docs, setDocs] = useState<KnowledgeDocument[] | null>(null);
  const [error, setError] = useState<UiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.listDocuments();
      setDocs(r.documents);
      setError(null);
    } catch (e) {
      setError(toUiError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, keyVersion]);

  useEffect(() => {
    window.addEventListener(REFRESH_EVENT, load);
    return () => window.removeEventListener(REFRESH_EVENT, load);
  }, [load]);

  const remove = async (source: string) => {
    setDeleting(source);
    try {
      const r = await api.deleteDocument(source);
      toast.success(`Deleted ${r.source} (${r.deleted_chunks} chunk${r.deleted_chunks === 1 ? "" : "s"})`);
      setConfirm(null);
      await load();
    } catch (e) {
      toast.error(e, `Could not delete ${source}`);
    } finally {
      setDeleting(null);
    }
  };

  const totalChunks = useMemo(() => (docs ?? []).reduce((n, d) => n + d.chunks, 0), [docs]);

  return (
    <div className="card kb-card">
      <div className="kb-card-head">
        <h2>Documents</h2>
        {docs && (
          <span className="muted">
            {docs.length} document{docs.length === 1 ? "" : "s"} · {totalChunks} chunks
          </span>
        )}
        <button
          className="btn btn-ghost btn-icon btn-sm"
          style={{ marginLeft: "auto" }}
          onClick={() => void load()}
          aria-label="Refresh documents"
          title="Refresh"
          disabled={loading}
        >
          <RefreshCw size={15} className={loading ? "spin" : ""} />
        </button>
      </div>

      {error && <ErrorBanner error={error} onRetry={() => void load()} title="Could not load documents" />}

      {!docs && !error && (
        <div className="doc-skeleton" aria-hidden>
          <div className="skeleton" />
          <div className="skeleton" />
          <div className="skeleton" />
        </div>
      )}

      {docs && docs.length === 0 && (
        <div className="empty">
          <Library size={28} aria-hidden />
          <strong>No documents yet</strong>
          <span>Upload a file to give the agent something to retrieve from.</span>
        </div>
      )}

      {docs && docs.length > 0 && (
        <ul className="docs">
          {docs.map((d) => (
            <li key={d.source} className="doc">
              <span className="doc-icon" aria-hidden>
                <FileText size={18} />
              </span>
              <div className="doc-main">
                <span className="doc-name truncate" title={d.source}>
                  {d.source}
                </span>
                <span className="muted">
                  {d.chunks} chunk{d.chunks === 1 ? "" : "s"}
                </span>
              </div>
              {confirm === d.source ? (
                <div className="doc-confirm">
                  <button className="btn btn-danger btn-sm" disabled={deleting === d.source} onClick={() => void remove(d.source)}>
                    {deleting === d.source ? <Loader2 size={14} className="spin" /> : <Trash2 size={14} />} Delete
                  </button>
                  <button className="btn btn-sm" onClick={() => setConfirm(null)}>
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  className="btn btn-ghost btn-icon btn-sm"
                  aria-label={`Delete ${d.source}`}
                  title="Delete"
                  onClick={() => setConfirm(d.source)}
                >
                  <Trash2 size={15} />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ search

function highlight(text: string, query: string): ReactNode {
  const terms = [...new Set(query.toLowerCase().match(/[\p{L}\p{N}]{2,}/gu) ?? [])];
  if (!terms.length) return text;
  const re = new RegExp(`(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "giu");
  return text.split(re).map((part, i) =>
    i % 2 === 1 ? (
      <mark key={i}>{part}</mark>
    ) : (
      <Fragment key={i}>{part}</Fragment>
    ),
  );
}

function SearchCard() {
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(5);
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [asked, setAsked] = useState("");
  const [error, setError] = useState<UiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [tookMs, setTookMs] = useState<number | null>(null);

  const run = async () => {
    const q = query.trim();
    if (!q || busy) return;
    setBusy(true);
    setError(null);
    const t0 = performance.now();
    try {
      const r = await api.search({ query: q, top_k: topK });
      setResults(r.results);
      setAsked(q);
      setTookMs(performance.now() - t0);
    } catch (e) {
      setError(toUiError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card kb-card kb-search">
      <div className="kb-card-head">
        <h2>Test search</h2>
        <span className="muted">What would the agent retrieve?</span>
      </div>
      <form
        className="search-form"
        onSubmit={(e) => {
          e.preventDefault();
          void run();
        }}
        role="search"
      >
        <div className="input-wrap" style={{ flex: 1, minWidth: 0 }}>
          <Search size={15} aria-hidden />
          <input
            className="input"
            placeholder="Ask something your documents should answer…"
            aria-label="Search query"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <label className="sr-only" htmlFor="kb-topk">
          Number of results
        </label>
        <select id="kb-topk" className="select topk" value={topK} onChange={(e) => setTopK(Number(e.target.value))}>
          {[3, 5, 8, 12].map((n) => (
            <option key={n} value={n}>
              Top {n}
            </option>
          ))}
        </select>
        <button type="submit" className="btn btn-primary" disabled={!query.trim() || busy}>
          {busy ? <Loader2 size={15} className="spin" /> : <Search size={15} />} Search
        </button>
      </form>

      {error && <ErrorBanner error={error} title="Search failed" onDismiss={() => setError(null)} />}

      {busy && !results && (
        <div className="doc-skeleton" aria-hidden>
          <div className="skeleton" style={{ height: 84 }} />
          <div className="skeleton" style={{ height: 84 }} />
        </div>
      )}

      {results && (
        <>
          <div className="muted result-count" role="status">
            {results.length === 0
              ? "No passages matched."
              : `${results.length} passage${results.length === 1 ? "" : "s"} for “${asked}”${tookMs != null ? ` · ${Math.round(tookMs)} ms` : ""}`}
          </div>
          <ol className="results">
            {results.map((r, i) => (
              <li key={`${r.source}-${r.chunk_index}-${i}`} className="result">
                <div className="result-head">
                  <span className="rank mono">{i + 1}</span>
                  <span className="result-src truncate" title={r.source}>
                    {r.source}
                  </span>
                  <span className="muted mono">#{r.chunk_index}</span>
                  <ScoreMeter score={r.score} />
                </div>
                <p className="result-text">{highlight(r.text, asked)}</p>
              </li>
            ))}
          </ol>
        </>
      )}

      {!results && !busy && !error && (
        <div className="empty">
          <Search size={28} aria-hidden />
          <strong>Try a retrieval query</strong>
          <span>Results show the matching passage, its source, chunk index and similarity score.</span>
        </div>
      )}
    </div>
  );
}

function ScoreMeter({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(1, score)) * 100;
  const tone = score >= 0.75 ? "hi" : score >= 0.5 ? "mid" : "lo";
  return (
    <span className={`score ${tone}`} title={`Similarity score ${score}`}>
      <span className="score-bar" aria-hidden>
        <i style={{ width: `${pct}%` }} />
      </span>
      <span className="mono">{score.toFixed(3)}</span>
    </span>
  );
}
