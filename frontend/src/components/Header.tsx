import { useRef, useState } from "react";
import { Eye, EyeOff, KeyRound, Moon, Monitor, PanelRight, Sun } from "lucide-react";
import { useHealth, useInfo } from "../hooks/useServerStatus";
import { useDismiss } from "../hooks/useDismiss";
import { formatUptime } from "../lib/format";
import { useInspector } from "../inspector/store";
import { useLayout, type View } from "../state/layout";
import { useSettings, type ThemeMode } from "../state/settings";
import { ErrorBanner } from "./ErrorBanner";
import type { InfoResponse } from "../api/types";

const TITLES: Record<View, { title: string; sub: string }> = {
  voice: { title: "Voice", sub: "Talk to the agent in real time" },
  chat: { title: "Text chat", sub: "Streaming answers over SSE" },
  knowledge: { title: "Knowledge", sub: "Documents the agent can retrieve from" },
};

export function Header() {
  const { view, toggleInspector, inspectorVisible, mobile } = useLayout();
  const { events } = useInspector();
  const { apiKey, theme, toggleTheme } = useSettings();
  const health = useHealth();
  const info = useInfo(health.status === "ok");
  const needsKey = info.data?.auth_required && !apiKey;
  const t = TITLES[view];

  return (
    <header className="topbar">
      <div className="topbar-title">
        <h1>{t.title}</h1>
        {!mobile && <p>{t.sub}</p>}
      </div>

      <HealthPill health={health} info={info.data} infoError={info.error?.message} />
      <RuntimeChips info={info.data} error={info.error?.message} />

      <div className="topbar-spacer" />

      <button
        className="btn btn-icon"
        aria-pressed={inspectorVisible}
        aria-label={inspectorVisible ? "Hide Inspector" : "Show Inspector"}
        title="Toggle Inspector"
        onClick={toggleInspector}
      >
        <PanelRight size={18} />
        {events.length > 0 && <span className="count-dot">{events.length > 99 ? "99+" : events.length}</span>}
      </button>
      <SettingsMenu needsKey={Boolean(needsKey)} />
      <button
        className="btn btn-icon"
        onClick={toggleTheme}
        aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
        title={theme === "dark" ? "Light theme" : "Dark theme"}
      >
        {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
      </button>
    </header>
  );
}

// ------------------------------------------------------------------ health

function HealthPill({
  health,
  info,
  infoError,
}: {
  health: ReturnType<typeof useHealth>;
  info?: InfoResponse;
  infoError?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useDismiss(ref, open, () => setOpen(false));

  const label = health.status === "ok" ? "Healthy" : health.status === "down" ? "Offline" : "Checking";
  const version = health.data?.version;

  return (
    <div className="menu-anchor" ref={ref}>
      <button
        className={`health-pill ${health.status}`}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={`API status: ${label}${version ? `, version ${version}` : ""}. Open details`}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="health-dot" aria-hidden />
        <span>{label}</span>
        {version && health.status === "ok" && <span className="health-ver">v{version}</span>}
      </button>

      {open && (
        <div className="popover" role="dialog" aria-label="Service status">
          <h2 className="pop-title">Service</h2>
          {health.status === "down" && health.error && (
            <div style={{ marginBottom: 12 }}>
              <ErrorBanner error={health.error} title="Health check failed" />
            </div>
          )}
          <dl className="kv">
            <dt>Status</dt>
            <dd>{label}</dd>
            {health.data?.service && (
              <>
                <dt>Service</dt>
                <dd>{health.data.service}</dd>
              </>
            )}
            {health.data?.version && (
              <>
                <dt>Version</dt>
                <dd>{health.data.version}</dd>
              </>
            )}
            {health.data?.env && (
              <>
                <dt>Environment</dt>
                <dd>{health.data.env}</dd>
              </>
            )}
            {health.data && Number.isFinite(health.data.uptime_seconds) && (
              <>
                <dt>Uptime</dt>
                <dd>{formatUptime(health.data.uptime_seconds)}</dd>
              </>
            )}
          </dl>
          <h2 className="pop-title" style={{ marginTop: 14 }}>
            Runtime
          </h2>
          {info ? (
            <dl className="kv">
              <dt>LLM</dt>
              <dd>{info.llm_model}</dd>
              <dt>STT</dt>
              <dd>
                {info.stt_provider} · {info.stt_model}
              </dd>
              <dt>TTS</dt>
              <dd>
                {info.tts_provider} · {info.tts_model}
              </dd>
              <dt>Turn detector</dt>
              <dd>{info.turn_detector}</dd>
              <dt>Embeddings</dt>
              <dd>{info.embedding_model}</dd>
              <dt>Tracing</dt>
              <dd>{info.tracing_provider}</dd>
              <dt>API key</dt>
              <dd>{info.auth_required ? "required" : "not required"}</dd>
            </dl>
          ) : (
            <p className="muted-note">{infoError ?? "Loading runtime info…"}</p>
          )}
          <div className="pop-actions">
            <button className="btn btn-sm" onClick={health.refresh}>
              Re-check now
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function RuntimeChips({ info, error }: { info?: InfoResponse; error?: string }) {
  if (!info) {
    return error ? (
      <div className="chips" aria-label="Runtime info">
        <span className="chip" title={error}>
          <b>info</b>
          <span>unavailable</span>
        </span>
      </div>
    ) : (
      <div className="chips" aria-hidden>
        <span className="skeleton" style={{ width: 120, height: 26, borderRadius: 999 }} />
      </div>
    );
  }
  const items: Array<[string, string]> = [
    ["LLM", info.llm_model],
    ["STT", `${info.stt_provider}/${info.stt_model}`],
    ["TTS", `${info.tts_provider}/${info.tts_model}`],
    ["Turn", info.turn_detector],
  ];
  return (
    <div className="chips" role="list" aria-label="Runtime info">
      {items.map(([k, v]) => (
        <span className="chip" role="listitem" key={k} title={`${k}: ${v}`}>
          <b>{k}</b>
          <span>{v}</span>
        </span>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ settings

const THEME_OPTIONS: Array<{ mode: ThemeMode; label: string; icon: typeof Sun }> = [
  { mode: "system", label: "System", icon: Monitor },
  { mode: "dark", label: "Dark", icon: Moon },
  { mode: "light", label: "Light", icon: Sun },
];

function SettingsMenu({ needsKey }: { needsKey: boolean }) {
  const { apiKey, setApiKey, themeMode, setThemeMode } = useSettings();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(apiKey);
  const [reveal, setReveal] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useDismiss(ref, open, () => setOpen(false));

  return (
    <div className="menu-anchor" ref={ref}>
      <button
        className="btn btn-icon"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label="API key and appearance"
        title="API key & appearance"
        onClick={() => {
          setDraft(apiKey);
          setOpen((o) => !o);
        }}
      >
        <KeyRound size={18} />
        {(apiKey || needsKey) && <span className={`key-dot${needsKey ? " warn" : ""}`} aria-hidden />}
      </button>

      {open && (
        <div className="popover" role="dialog" aria-label="API key and appearance">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setApiKey(draft);
              setOpen(false);
            }}
          >
            <label className="field-label" htmlFor="api-key">
              API key
            </label>
            <div className="input-wrap">
              <KeyRound size={15} aria-hidden />
              <input
                id="api-key"
                className="input mono"
                type={reveal ? "text" : "password"}
                autoComplete="off"
                spellCheck={false}
                placeholder={needsKey ? "Required by this server" : "Optional"}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                style={{ paddingRight: 40 }}
              />
              <button
                type="button"
                className="btn btn-ghost btn-icon btn-sm reveal"
                aria-label={reveal ? "Hide key" : "Show key"}
                onClick={() => setReveal((r) => !r)}
              >
                {reveal ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
            </div>
            <p className="muted-note">Sent as the X-API-Key header. Stored only in this browser (localStorage).</p>
            <div className="pop-actions">
              <button
                type="button"
                className="btn btn-sm"
                disabled={!apiKey && !draft}
                onClick={() => {
                  setDraft("");
                  setApiKey("");
                }}
              >
                Clear
              </button>
              <button type="submit" className="btn btn-primary btn-sm">
                Save
              </button>
            </div>
          </form>

          <h2 className="pop-title" style={{ marginTop: 16 }}>
            Theme
          </h2>
          <div className="segmented" role="radiogroup" aria-label="Theme">
            {THEME_OPTIONS.map(({ mode, label, icon: Icon }) => (
              <button
                key={mode}
                type="button"
                role="radio"
                aria-checked={themeMode === mode}
                className={themeMode === mode ? "on" : ""}
                onClick={() => setThemeMode(mode)}
              >
                <Icon size={14} /> {label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
