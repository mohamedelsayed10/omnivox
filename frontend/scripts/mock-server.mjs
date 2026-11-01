/**
 * DEV-ONLY mock of the OmniVox backend contract.
 *
 * Not part of the product and never bundled: it exists so the GUI can be built
 * and demoed while the real FastAPI backend is not running. Zero dependencies.
 *
 *   npm run mock               # http://localhost:8787
 *   MOCK_PORT=8100 npm run mock
 *   MOCK_API_KEY=secret npm run mock   # require X-API-Key (exercises the 401 path)
 *
 * Besides the contract endpoints it exposes one non-contract route used by the
 * GUI's dev-only "Simulate call" button:
 *   GET /__mock/trace?speed=1   SSE replay of sample `omnivox.trace` events
 */
import http from "node:http";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";

const STARTED = Date.now();
const MODEL = "gemini-2.5-flash";

// ------------------------------------------------------------------ helpers

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const rid = () => "req_" + randomUUID().replace(/-/g, "").slice(0, 12);

function cors(res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, X-API-Key, Accept");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS");
  res.setHeader("Access-Control-Expose-Headers", "X-Request-ID");
}

function sendJson(res, status, body) {
  const text = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(text),
  });
  res.end(text);
}

function sendError(res, status, code, message, details) {
  sendJson(res, status, {
    error: { code, message, request_id: res.getHeader("X-Request-ID"), ...(details ? { details } : {}) },
  });
}

async function readBody(req) {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  return Buffer.concat(chunks);
}

async function readJson(req, res) {
  const raw = await readBody(req);
  try {
    return JSON.parse(raw.toString("utf8") || "{}");
  } catch {
    sendError(res, 400, "invalid_json", "Request body is not valid JSON.");
    return null;
  }
}

function sse(res, event, data) {
  res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
}

function startSse(res) {
  res.writeHead(200, {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-store",
    Connection: "keep-alive",
    "X-Accel-Buffering": "no",
  });
  res.write(": stream open\n\n");
}

/** Minimal multipart/form-data parser: returns {fields, file:{name, data}}. */
function parseMultipart(buf, contentType) {
  const m = /boundary=(?:"([^"]+)"|([^;]+))/i.exec(contentType || "");
  if (!m) return null;
  const boundary = Buffer.from("--" + (m[1] || m[2]).trim());
  const fields = {};
  let file = null;
  let pos = buf.indexOf(boundary);
  while (pos !== -1) {
    const next = buf.indexOf(boundary, pos + boundary.length);
    if (next === -1) break;
    let seg = buf.subarray(pos + boundary.length, next);
    if (seg[0] === 13 && seg[1] === 10) seg = seg.subarray(2);
    if (seg.length >= 2 && seg[seg.length - 2] === 13 && seg[seg.length - 1] === 10) {
      seg = seg.subarray(0, seg.length - 2);
    }
    const headEnd = seg.indexOf("\r\n\r\n");
    if (headEnd !== -1) {
      const head = seg.subarray(0, headEnd).toString("utf8");
      const body = seg.subarray(headEnd + 4);
      const name = /name="([^"]*)"/i.exec(head)?.[1];
      const filename = /filename="([^"]*)"/i.exec(head)?.[1];
      if (name === "file" && filename !== undefined) file = { name: filename, data: body };
      else if (name) fields[name] = body.toString("utf8");
    }
    pos = next;
  }
  return { fields, file };
}

// ------------------------------------------------------------------ knowledge store

const store = new Map(); // source -> string[] (chunks)

function chunkText(text) {
  const paras = text.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);
  const chunks = [];
  let cur = "";
  for (const p of paras.length ? paras : [text.trim()]) {
    if (cur && (cur + "\n\n" + p).length > 700) {
      chunks.push(cur);
      cur = p;
    } else cur = cur ? cur + "\n\n" + p : p;
  }
  if (cur) chunks.push(cur);
  while (chunks.some((c) => c.length > 900)) {
    const i = chunks.findIndex((c) => c.length > 900);
    const c = chunks[i];
    chunks.splice(i, 1, c.slice(0, 700), c.slice(700));
  }
  return chunks.length ? chunks : [text];
}

store.set("omnivox-overview.md", [
  "# OmniVox architecture\n\nOmniVox is a real-time voice agent. Audio flows from the browser microphone through LiveKit to the agent worker, where a voice activity detector (VAD) segments speech, a streaming speech-to-text model produces a transcript, and an end-of-turn model decides when the user has finished speaking.",
  "The finished turn is handed to a LangGraph agent. The graph routes between a plain answer, a web search tool (ddgs) and a retrieval tool that queries a Qdrant vector store. The language model is Gemini, reached through an OpenAI-compatible API.",
  "Replies stream back token by token into text-to-speech, so the first audio can play before the model has finished writing. Every stage emits trace events on the LiveKit data channel, topic omnivox.trace, which the Inspector renders as a per-turn timeline.",
  "## Latency budget\n\nThe target for a spoken reply is under 1.5 seconds from the end of speech to the first audio: roughly 400 ms for end-of-turn detection, 700 ms until the first LLM token, and 300 ms for TTS time-to-first-byte.",
]);
store.set("livekit-agents-notes.txt", [
  "LiveKit rooms are created on first join. The agent worker is dispatched automatically when a participant connects, so the browser only needs a token from POST /api/v1/livekit/token and the websocket url returned with it.",
  "Interruptions: when the user starts speaking while the agent is talking, the session cancels TTS playback and returns to the listening state. The VAD user_state event moves from listening to speaking.",
  "Transcripts are published as text streams on the lk.transcription topic; trace events are separate and use the omnivox.trace topic with reliable delivery.",
]);
store.set("onboarding-faq.pdf", [
  "Q: Which file types can I upload to the knowledge base? A: Plain text (.txt), Markdown (.md) and PDF (.pdf). Each file is split into overlapping chunks of roughly 700 characters and embedded.",
  "Q: How do I remove a document? A: Use the delete action in the document list. All chunks for that source are removed from the vector store.",
  "Q: Why does the agent not cite my document? A: Use the test search box to check whether the relevant passage scores above the retrieval threshold.",
]);

const tokenize = (s) => s.toLowerCase().match(/[a-z0-9]{3,}/g) ?? [];

function search(query, topK) {
  const terms = [...new Set(tokenize(query))];
  const out = [];
  for (const [source, chunks] of store) {
    chunks.forEach((text, chunk_index) => {
      const hay = tokenize(text);
      const set = new Set(hay);
      const hits = terms.filter((t) => set.has(t) || hay.some((h) => h.startsWith(t) || t.startsWith(h))).length;
      if (!hits) return;
      const jitter = ((chunk_index * 7 + source.length) % 10) / 100;
      const score = Math.min(0.97, 0.38 + 0.55 * (hits / Math.max(1, terms.length)) + jitter);
      out.push({ source, chunk_index, score: Math.round(score * 1000) / 1000, text });
    });
  }
  return out.sort((a, b) => b.score - a.score).slice(0, topK);
}

// ------------------------------------------------------------------ agent behaviour

function plan(message) {
  const m = message.toLowerCase();
  const web = /search|web|news|weather|latest|today|release|price/.test(m);
  const rag = /document|knowledge|docs?\b|rag|uploaded|omnivox|latency|architecture|file/.test(m);
  return { web, rag };
}

function composeAnswer(message, tools) {
  const lines = [];
  if (tools.includes("rag_search")) {
    lines.push("Here is what the knowledge base says:");
    lines.push("");
    lines.push("- **Pipeline:** microphone → LiveKit → VAD → STT → end-of-turn model → LangGraph agent → TTS.");
    lines.push("- **Latency budget:** under 1.5 s from end of speech to first audio.");
    lines.push("- **Retrieval:** documents are chunked (~700 chars) and stored in `Qdrant`.");
  }
  if (tools.includes("web_search")) {
    if (lines.length) lines.push("");
    lines.push("From a quick web search I found three recent results; the most relevant one is from the official release notes.");
  }
  if (!lines.length) {
    lines.push(`You said: "${message.slice(0, 120)}".`);
    lines.push("");
    lines.push("I can answer from the uploaded documents or search the web. Try asking about the **OmniVox architecture** or to *search the web* for something recent.");
  }
  return lines.join("\n");
}

function* wordsOf(text) {
  const parts = text.match(/\S+\s*|\n+/g) ?? [];
  yield* parts;
}

async function handleInvoke(req, res) {
  const body = await readJson(req, res);
  if (!body) return;
  if (!validAgentBody(body, res)) return;
  const p = plan(body.message);
  const tools = [p.rag && "rag_search", p.web && "web_search"].filter(Boolean);
  await sleep(500);
  sendJson(res, 200, {
    session_id: body.session_id,
    answer: composeAnswer(body.message, tools),
    tools_used: tools,
    request_id: res.getHeader("X-Request-ID"),
  });
}

function validAgentBody(body, res) {
  const sid = body.session_id;
  if (typeof sid !== "string" || sid.length < 1 || sid.length > 64) {
    sendError(res, 422, "validation_error", "session_id must be a string of 1 to 64 characters.", [
      { loc: ["body", "session_id"], msg: "length must be between 1 and 64" },
    ]);
    return false;
  }
  if (typeof body.message !== "string" || !body.message.trim()) {
    sendError(res, 422, "validation_error", "message must be a non-empty string.", [
      { loc: ["body", "message"], msg: "field required" },
    ]);
    return false;
  }
  return true;
}

async function handleStream(req, res) {
  const body = await readJson(req, res);
  if (!body) return;
  if (!validAgentBody(body, res)) return;
  const text = body.message;
  if (/\/boom\b/i.test(text)) {
    return sendError(res, 502, "upstream_error", "The LLM provider returned HTTP 503 (model overloaded).", {
      provider: "gemini",
    });
  }

  const p = plan(text);
  const tools = [p.rag && "rag_search", p.web && "web_search"].filter(Boolean);
  let closed = false;
  req.on("close", () => (closed = true));
  startSse(res);

  const emit = (event, data) => !closed && sse(res, event, data);

  emit("node", { name: "router", phase: "start" });
  await sleep(120);
  emit("node", { name: "router", phase: "end", duration_ms: 118 });

  if (/\/error\b/i.test(text)) {
    emit("node", { name: "agent", phase: "start" });
    await sleep(300);
    emit("error", { code: "llm_error", message: "The model stream was interrupted.", request_id: res.getHeader("X-Request-ID") });
    return res.end();
  }

  emit("node", { name: "agent", phase: "start" });
  for (const tool of tools) {
    const args = tool === "web_search" ? { query: text.slice(0, 80), max_results: 3 } : { query: text.slice(0, 80), top_k: 4 };
    emit("tool", { name: tool, phase: "start", args });
    const dur = tool === "web_search" ? 820 : 260;
    await sleep(dur);
    if (tool === "web_search" && /\/toolfail\b/i.test(text)) {
      emit("tool", { name: tool, phase: "error", message: "ddgs timeout after 5000 ms", duration_ms: dur });
      continue;
    }
    const preview =
      tool === "web_search"
        ? "1. Qdrant 1.15 release notes: faster filtered search… 2. LiveKit Agents 1.x changelog… 3. Gemini API pricing update…"
        : "[omnivox-overview.md#0] OmniVox is a real-time voice agent. Audio flows from the browser microphone…";
    emit("tool", { name: tool, phase: "end", result_preview: preview, duration_ms: dur });
  }

  await sleep(260);
  const answer = composeAnswer(text, tools);
  for (const w of wordsOf(answer)) {
    if (closed) return res.end();
    emit("token", { text: w });
    await sleep(22);
  }
  emit("node", { name: "agent", phase: "end", duration_ms: 1500 });
  emit("final", { answer, session_id: body.session_id });
  res.end();
}

// ------------------------------------------------------------------ trace replay (dev only)

/**
 * Each scenario yields {at, kind, payload} entries relative to the turn start.
 * Payloads for kind "trace" follow the documented v1 envelope exactly. Two
 * scenarios deliberately include event types the GUI does not know about.
 */
function buildTurn(turn, sc) {
  const out = [];
  let seq = 0;
  const trace = (at, source, type, label, data, duration_ms) =>
    out.push({ at, kind: "trace", payload: { v: 1, id: `evt_${turn}_${++seq}`, turn, source, type, label, ...(duration_ms != null ? { duration_ms } : {}), data } });
  const say = (at, role, text, final) => out.push({ at, kind: "transcript", payload: { role, text, final } });

  const words = sc.user.split(" ");
  const speechEnd = 300 + words.length * 260;
  trace(0, "vad", "user_state", "User started speaking", { state: "speaking" });
  words.forEach((_, i) => {
    if (i % 2 === 1 || i === words.length - 1) {
      const t = words.slice(0, i + 1).join(" ");
      trace(300 + i * 260, "stt", "interim", "Interim transcript", { text: t });
    }
  });
  trace(speechEnd, "vad", "user_state", "User stopped speaking", { state: "listening" });
  trace(speechEnd + 140, "stt", "final", "Final transcript", { text: sc.user, language: "en" });
  const eotAt = speechEnd + sc.eot;
  trace(eotAt, "eot", "detected", "End of turn", { delay_ms: sc.eot, transcript_delay_ms: 140 });
  trace(eotAt + 20, "session", "agent_state", "Agent thinking", { state: "thinking" });

  let t = eotAt + 30;
  trace(t, "graph", "node_start", "Node router", { node: "router" });
  trace((t += 44), "graph", "node_end", "Node router", { node: "router" }, 44);
  trace((t += 2), "graph", "route", `Route router → ${sc.route}`, { from: "router", to: sc.route });
  trace((t += 4), "graph", "node_start", `Node ${sc.route}`, { node: sc.route });
  const nodeStart = t;
  for (const tool of sc.tools) {
    trace((t += 6), "tool", "start", `Tool ${tool.name}`, { name: tool.name, args: tool.args });
    if (tool.error) {
      trace((t += tool.ms), "tool", "error", `Tool ${tool.name} failed`, { name: tool.name, message: tool.error }, tool.ms);
      trace(t + 2, "error", "error", "Tool error (recovered)", { message: `${tool.name} failed; answered without it`, source: "tool" });
    } else {
      trace((t += tool.ms), "tool", "end", `Tool ${tool.name}`, { name: tool.name, result_preview: tool.preview }, tool.ms);
    }
  }
  if (sc.extra) sc.extra(trace, t);
  const llmStart = t + 8;
  trace(llmStart, "llm", "start", "LLM request", { model: MODEL });
  const firstTok = llmStart + sc.ttft;
  trace(firstTok, "llm", "first_token", "First token", { ttft_ms: sc.ttft });
  trace(firstTok + 6, "session", "agent_state", "Agent speaking", { state: "speaking" });
  const ttsStart = firstTok + 20;
  trace(ttsStart, "tts", "start", "TTS synthesis", { characters: sc.answer.length });
  const firstAudio = ttsStart + sc.ttfb;
  trace(firstAudio, "tts", "first_audio", "First audio", { ttfb_ms: sc.ttfb });
  const llm_ttft_ms = firstTok - eotAt;
  trace(firstAudio + 4, "latency", "turn_summary", "Turn latency", {
    eot_ms: sc.eot,
    llm_ttft_ms,
    tts_ttfb_ms: sc.ttfb + 20,
    total_ms: sc.eot + llm_ttft_ms + sc.ttfb + 20,
  });
  const llmEnd = firstAudio + 700;
  trace(llmEnd, "llm", "end", "LLM done", { input_tokens: sc.inTok, output_tokens: sc.outTok, finish_reason: "stop" }, llmEnd - llmStart);
  trace(llmEnd + 6, "graph", "node_end", `Node ${sc.route}`, { node: sc.route }, llmEnd + 6 - nodeStart);
  const audioMs = Math.max(2400, sc.answer.length * 38);
  const ttsEnd = firstAudio + audioMs;
  trace(ttsEnd, "tts", "end", "TTS done", { audio_ms: audioMs }, ttsEnd - ttsStart);
  trace(ttsEnd + 10, "session", "agent_state", "Agent listening", { state: "listening" });

  // Agent transcript grows while audio plays.
  const aw = sc.answer.split(" ");
  const steps = Math.min(aw.length, 8);
  for (let i = 1; i <= steps; i++) {
    const n = Math.ceil((aw.length * i) / steps);
    say(firstAudio + ((audioMs * i) / steps) * 0.9, "agent", aw.slice(0, n).join(" "), i === steps);
  }
  return { events: out.sort((a, b) => a.at - b.at), length: ttsEnd + 600 };
}

const SCENARIOS = [
  {
    user: "What does the knowledge base say about the latency budget?",
    route: "rag_agent",
    eot: 380,
    ttft: 590,
    ttfb: 310,
    inTok: 1184,
    outTok: 96,
    answer: "The target is under one and a half seconds from the end of your speech to the first audio, roughly four hundred milliseconds for end of turn, seven hundred for the first token and three hundred for text to speech.",
    tools: [{ name: "rag_search", args: { query: "latency budget", top_k: 4 }, ms: 240, preview: "[omnivox-overview.md#3] The target for a spoken reply is under 1.5 seconds from the end of speech to the first audio…" }],
  },
  {
    user: "Search the web for the latest Qdrant release",
    route: "web_agent",
    eot: 420,
    ttft: 710,
    ttfb: 340,
    inTok: 902,
    outTok: 71,
    answer: "The most recent Qdrant release focuses on faster filtered search and lower memory use. I would check the official release notes for the exact version number.",
    tools: [{ name: "web_search", args: { query: "latest Qdrant release", max_results: 3 }, ms: 840, preview: "1. Qdrant 1.15 release notes: faster filtered search… 2. Qdrant blog… 3. GitHub releases…" }],
    // Forward compatibility: events the GUI has never seen must still render.
    extra: (trace, t) => {
      trace(t + 3, "llm", "cache_hit", "Prompt cache hit", { cached_tokens: 768, prefix: "system+tools" });
      trace(t + 4, "memory", "recall", "Conversation memory recalled", { items: 2, store: "session" });
    },
  },
  {
    user: "And what is the weather in Cairo today",
    route: "web_agent",
    eot: 350,
    ttft: 480,
    ttfb: 290,
    inTok: 640,
    outTok: 38,
    answer: "I could not reach the weather search just now, so I cannot give you a live forecast. Cairo is usually hot and dry at this time of year.",
    tools: [{ name: "web_search", args: { query: "weather Cairo today" }, ms: 5000, error: "ddgs timeout after 5000 ms" }],
  },
];

async function handleTraceReplay(req, res, url) {
  const speed = Math.max(0.25, Number(url.searchParams.get("speed")) || 1);
  const count = Math.min(SCENARIOS.length, Number(url.searchParams.get("turns")) || SCENARIOS.length);
  let closed = false;
  req.on("close", () => (closed = true));
  startSse(res);

  // Session-level events (turn 0), as the agent emits on join.
  const hello = (type, label, data) => ({ v: 1, id: `evt_0_${type}`, ts: Date.now(), turn: 0, source: "session", type, label, data });
  sse(res, "trace", hello("agent_state", "Agent initializing", { state: "initializing" }));
  await sleep(500 / speed);
  sse(res, "trace", hello("agent_state", "Agent listening", { state: "listening" }));
  await sleep(900 / speed);

  for (let i = 0; i < count; i++) {
    const turn = buildTurn(i + 1, SCENARIOS[i]);
    const start = Date.now();
    for (const ev of turn.events) {
      const wait = ev.at / speed - (Date.now() - start);
      if (wait > 0) await sleep(wait);
      if (closed) return res.end();
      if (ev.kind === "trace") ev.payload.ts = Date.now();
      sse(res, ev.kind, ev.payload);
    }
    await sleep(900 / speed);
  }
  sse(res, "done", { turns: count });
  res.end();
}

// ------------------------------------------------------------------ router

const API_KEY = process.env.MOCK_API_KEY || "";

export function createMockServer() {
  return http.createServer(async (req, res) => {
    const url = new URL(req.url ?? "/", "http://mock");
    const path = url.pathname.replace(/\/+$/, "") || "/";
    res.setHeader("X-Request-ID", rid());
    cors(res);
    if (req.method === "OPTIONS") {
      res.writeHead(204);
      return res.end();
    }

    try {
      if (path === "/health" && req.method === "GET") {
        return sendJson(res, 200, {
          status: "ok",
          service: "omnivox",
          version: "0.1.0-mock",
          env: "mock",
          uptime_seconds: Math.round((Date.now() - STARTED) / 1000),
        });
      }
      if (path === "/__mock/trace" && req.method === "GET") return await handleTraceReplay(req, res, url);

      if (!path.startsWith("/api/v1")) return sendError(res, 404, "not_found", `No route for ${req.method} ${path}.`);

      if (path === "/api/v1/info" && req.method === "GET") {
        return sendJson(res, 200, {
          app_name: "OmniVox",
          version: "0.1.0-mock",
          llm_model: MODEL,
          stt_provider: "deepgram",
          stt_model: "nova-3",
          tts_provider: "cartesia",
          tts_model: "sonic-2",
          embedding_model: "text-embedding-004",
          turn_detector: "livekit/turn-detector (multilingual)",
          tracing_provider: "none",
          auth_required: Boolean(API_KEY),
        });
      }

      if (API_KEY && req.headers["x-api-key"] !== API_KEY) {
        return sendError(res, 401, "unauthorized", "Missing or invalid API key.");
      }

      if (path === "/api/v1/livekit/token" && req.method === "POST") {
        const body = await readJson(req, res);
        if (!body) return;
        return sendJson(res, 200, {
          token: "mock.jwt.token",
          url: "ws://localhost:7880",
          room: body.room || "omnivox-" + randomUUID().slice(0, 6),
          identity: body.identity || "web-" + randomUUID().slice(0, 6),
        });
      }
      if (path === "/api/v1/agent/invoke" && req.method === "POST") return await handleInvoke(req, res);
      if (path === "/api/v1/agent/stream" && req.method === "POST") return await handleStream(req, res);

      if (path === "/api/v1/knowledge/documents" && req.method === "GET") {
        return sendJson(res, 200, { documents: [...store].map(([source, c]) => ({ source, chunks: c.length })) });
      }
      if (path === "/api/v1/knowledge/documents" && req.method === "POST") {
        const parsed = parseMultipart(await readBody(req), req.headers["content-type"]);
        if (!parsed?.file) return sendError(res, 422, "validation_error", "Multipart field 'file' is required.");
        const name = parsed.file.name;
        const ext = name.split(".").pop()?.toLowerCase();
        if (!["txt", "md", "pdf"].includes(ext ?? "")) {
          return sendError(res, 415, "unsupported_media_type", `Unsupported file type '.${ext}'. Use txt, md or pdf.`);
        }
        await sleep(700);
        const text =
          ext === "pdf"
            ? `[mock text extracted from ${name}] `.repeat(Math.max(3, Math.round(parsed.file.data.length / 600)))
            : parsed.file.data.toString("utf8");
        if (!text.trim()) return sendError(res, 422, "empty_document", "The document contains no extractable text.");
        const source = (parsed.fields.source || name).trim();
        const chunks = chunkText(text);
        store.set(source, chunks);
        return sendJson(res, 200, { source, chunks: chunks.length, characters: text.length });
      }
      const del = /^\/api\/v1\/knowledge\/documents\/(.+)$/.exec(path);
      if (del && req.method === "DELETE") {
        const source = decodeURIComponent(del[1]);
        const chunks = store.get(source);
        if (!chunks) return sendError(res, 404, "document_not_found", `No document named '${source}'.`);
        store.delete(source);
        return sendJson(res, 200, { source, deleted_chunks: chunks.length });
      }
      if (path === "/api/v1/knowledge/search" && req.method === "POST") {
        const body = await readJson(req, res);
        if (!body) return;
        if (typeof body.query !== "string" || !body.query.trim()) {
          return sendError(res, 422, "validation_error", "query must be a non-empty string.");
        }
        await sleep(250);
        return sendJson(res, 200, { results: search(body.query, Math.min(20, Number(body.top_k) || 5)) });
      }

      return sendError(res, 404, "not_found", `No route for ${req.method} ${path}.`);
    } catch (e) {
      console.error("[mock] handler failed:", e);
      if (!res.headersSent) sendError(res, 500, "internal_error", "Mock server error: " + (e?.message ?? e));
      else res.end();
    }
  });
}

export function startMockServer(port = Number(process.env.MOCK_PORT) || 8787) {
  return new Promise((resolve, reject) => {
    const server = createMockServer();
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => {
      console.log(`[mock] OmniVox dev mock listening on http://localhost:${port}${API_KEY ? " (X-API-Key required)" : ""}`);
      resolve(server);
    });
  });
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  startMockServer().catch((e) => {
    console.error("[mock] failed to start:", e.message);
    process.exit(1);
  });
}
