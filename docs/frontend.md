# OmniVox web GUI

A Vite + React + TypeScript (`strict`) single-page app in [`frontend/`](../frontend). Plain CSS with design tokens
(dark by default, `prefers-color-scheme` and a manual toggle), `lucide-react` icons, `livekit-client` and
`@livekit/components-react` for the voice path. No UI framework.

Views (left rail, or a bottom tab bar on phones): **Voice**, **Text chat**, **Knowledge**. Every view shares the
**Inspector**, a collapsible, resizable right panel (an overlay drawer / bottom sheet on narrow screens) that shows the
agent's internal steps.

## Scripts

Run from `frontend/`.

| Script                | What it does                                                                                   |
| --------------------- | ---------------------------------------------------------------------------------------------- |
| `npm run dev`         | Vite dev server on `:5173`; proxies `/api` and `/health` to the backend.                        |
| `npm run dev:mock`    | Same, plus the dev-only mock backend (`frontend/scripts/mock-server.mjs`, port `8787`) wired in.         |
| `npm run mock`        | Only the mock backend. `MOCK_PORT=8100` to change the port, `MOCK_API_KEY=secret` to require `X-API-Key`. |
| `npm run build`       | `tsc -b` (strict) then `vite build` into `frontend/dist`.                                       |
| `npm run typecheck`   | `tsc -b` only.                                                                                  |
| `npm run preview`     | Serve `dist` on `:4173` with the same proxy.                                                    |

## Environment

| Variable            | Default                 | Meaning                                                              |
| ------------------- | ----------------------- | -------------------------------------------------------------------- |
| `VITE_API_BASE_URL` | `http://localhost:8100` | Where the dev/preview server proxies `/api` and `/health` (`frontend/.env.example`). |

The browser always calls same-origin relative URLs. For production serve `dist/` from the backend (or a reverse proxy
that also forwards `/api` and `/health`). The LiveKit URL comes from `POST /api/v1/livekit/token`; it must be reachable
from the browser. The API key (header `X-API-Key`) is stored in `localStorage` under `omnivox.apiKey`.

Dev-only URL parameters: `?theme=light|dark` (not persisted), `?demo` (start the sample-call replay on load, needs the
mock) and `&speed=3` (replay speed).

## Layout

```
frontend/
  scripts/mock-server.mjs    DEV ONLY mock of the whole contract + sample trace replay (no deps)
  scripts/dev-with-mock.mjs  DEV ONLY: mock + Vite together
  src/
    api/types.ts             every request/response/trace type (single source)
    api/client.ts            typed fetch client, ApiError (message, code, request_id), SSE parser, streamAgent()
    inspector/               store.ts (event store), describe.ts (summaries), Inspector/Timeline/Waterfall/LatencyPanel
    state/                   settings (theme, API key), layout (route, inspector size), chat, voice, toast
    views/                   VoiceView, ChatView, KnowledgeView
    components/              Header, Rail, Orb (canvas), Markdown, ErrorBanner, CopyButton
    dev/                     DemoProvider: replays the mock's sample call; not mounted in production builds
    styles/                  tokens.css (themes), base.css, layout.css, one file per view + inspector.css
```

## How the Inspector consumes events

All events, from any source, go through one store (`inspector/store.ts`) and one shape, the v1 envelope
`{v,id,ts,turn,source,type,label,duration_ms?,data}`:

- **Voice.** `state/voice.tsx` listens to `RoomEvent.DataReceived` and forwards payloads with topic `omnivox.trace` to
  `inspectorStore.ingestRaw()`, which JSON-decodes and normalises them. Each connect starts a new *run* ("Voice call N").
- **Text chat.** `inspector/chatTrace.ts` maps the SSE frames of `POST /agent/stream` onto the same shape: `node` to
  `graph.node_start|node_end`, `tool` to `tool.start|end|error`, the first `token` to `llm.first_token` (client-measured),
  `final` to `session.final` plus a partial `latency.turn_summary`, `error` to `error.error`. Each message is one turn.
- **Robustness.** Unknown sources and types are accepted: they render with a neutral badge, a dashed
  `source.type` tag and a generic summary of the first fields of `data`. Missing optional fields are defaulted;
  frames that are not JSON objects are dropped and counted ("N malformed frames ignored"). Events are de-duplicated by
  `id` within a run and capped at 6000 (oldest trimmed, with a notice).
- **Grouping.** Events are grouped by `run:turn` into collapsible cards (latest turn open by default). `turn: 0` is the
  "Session" card. Rows show the offset from the turn's first event, a colour-coded source badge, label, summary and
  `duration_ms`; clicking expands the pretty-printed `data`.
- **Controls.** Source filter chips (counts always reflect all events), text search over source/type/label/data,
  pause (new events are buffered, not lost, and flushed on resume), clear, export JSON (all captured events plus
  runs), auto-scroll (turns itself off when you scroll up). The handle on the panel's left edge resizes it
  (drag, or arrow keys; Shift for bigger steps; double-click resets).
- **Latency.** `latency.turn_summary` `{eot_ms, llm_ttft_ms, tts_ttfb_ms, total_ms}` is drawn as a sequential
  waterfall (speech end, end-of-turn, LLM first token, TTS first audio) inside each turn card, and again on the
  **Latency** tab on one shared time axis with last/average/median/slowest. Stages a summary lacks are omitted.

## Voice view

`state/voice.tsx` owns one LiveKit `Room` for the whole app, so a call survives switching views. The agent state comes
from `useVoiceAssistant()` (falling back to `session.agent_state` trace events); the user's transcript comes from
`stt.interim|final` trace events and the agent's text from LiveKit transcription streams (`useTranscriptions()`).
Connection problems are mapped to plain messages (token failure with `request_id`, LiveKit unreachable, token rejected,
mic blocked / not found / in use, agent never joined within 20 s). The mic list is enumerated without prompting; the
browser asks for permission only when a call starts.

## Verification notes

Developed against the mock. The real WebRTC media path (mic capture, agent audio playback, the orb reacting to real
levels) needs a running LiveKit server and agent worker and could not be exercised without them; the dev-only
**Simulate call** button replays a scripted call through the same Inspector/transcript code path instead.
