import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  ConnectionError,
  ConnectionErrorReason,
  ConnectionState,
  createAudioAnalyser,
  DisconnectReason,
  MediaDeviceFailure,
  Room,
  RoomEvent,
  Track,
  type LocalAudioTrack,
  type RemoteAudioTrack,
} from "livekit-client";
import {
  RoomAudioRenderer,
  RoomContext,
  useConnectionState,
  useLocalParticipant,
  useTranscriptions,
  useVoiceAssistant,
} from "@livekit/components-react";
import { api } from "../api/client";
import { TRACE_TOPIC, type TokenResponse } from "../api/types";
import { toUiError, type UiError } from "../components/ErrorBanner";
import { useDemo } from "../dev/demoContext";
import { useTraceTranscript } from "../hooks/useTraceTranscript";
import { inspectorStore } from "../inspector/store";
import type { TranscriptEntry, VoiceSession, VoiceState } from "./voiceTypes";

const LiveCtx = createContext<VoiceSession | null>(null);

/** The session the Voice view should render: the dev replay while it runs, LiveKit otherwise. */
export function useVoiceSession(): VoiceSession {
  const live = useContext(LiveCtx);
  const demo = useDemo();
  if (!live) throw new Error("useVoiceSession outside VoiceProvider");
  return demo?.active ? demo.session : live;
}

/** Owns the LiveKit Room for the whole app so a call survives switching views. */
export function VoiceProvider({ children }: { children: ReactNode }) {
  const [room] = useState(
    () =>
      new Room({
        adaptiveStream: true,
        dynacast: true,
        audioCaptureDefaults: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      }),
  );

  useEffect(() => () => void room.disconnect(), [room]);

  return (
    <RoomContext.Provider value={room}>
      <RoomAudioRenderer />
      <LiveSession room={room}>{children}</LiveSession>
    </RoomContext.Provider>
  );
}

// ------------------------------------------------------------------ helpers

/** Poll an audio track's volume into a ref (read by the orb each frame without re-rendering). */
function useLevelRef(track: LocalAudioTrack | RemoteAudioTrack | undefined) {
  const ref = useRef(0);
  useEffect(() => {
    if (!track) {
      ref.current = 0;
      return;
    }
    let raf = 0;
    let cleanup: (() => Promise<void>) | undefined;
    try {
      const a = createAudioAnalyser(track, { fftSize: 512, smoothingTimeConstant: 0.5 });
      cleanup = a.cleanup;
      const loop = () => {
        ref.current = Math.min(1, a.calculateVolume());
        raf = requestAnimationFrame(loop);
      };
      raf = requestAnimationFrame(loop);
    } catch {
      ref.current = 0;
    }
    return () => {
      cancelAnimationFrame(raf);
      ref.current = 0;
      void cleanup?.();
    };
  }, [track]);
  return ref;
}

function micErrorMessage(e: unknown): string {
  if (!window.isSecureContext) {
    return "Microphone access needs a secure context: open this page over HTTPS or on localhost.";
  }
  switch (MediaDeviceFailure.getFailure(e)) {
    case MediaDeviceFailure.PermissionDenied:
      return "Microphone access was blocked. Allow the microphone for this site in your browser settings, then try again.";
    case MediaDeviceFailure.NotFound:
      return "No microphone was found. Plug one in or pick another input device.";
    case MediaDeviceFailure.DeviceInUse:
      return "The microphone is in use by another application.";
    default:
      return `Could not start the microphone${e instanceof Error ? `: ${e.message}` : "."}`;
  }
}

function connectionErrorMessage(e: unknown, url: string): UiError {
  if (e instanceof ConnectionError) {
    switch (e.reason) {
      case ConnectionErrorReason.NotAllowed:
        return {
          message: "LiveKit rejected the access token. Check the API key/secret the backend signs tokens with.",
          code: "livekit_not_allowed",
        };
      case ConnectionErrorReason.ServerUnreachable:
      case ConnectionErrorReason.WebSocket:
      case ConnectionErrorReason.Timeout:
        return {
          message: `Could not reach the LiveKit server at ${url}. Check that LiveKit is running and reachable from this browser.`,
          code: "livekit_unreachable",
        };
      case ConnectionErrorReason.Cancelled:
        return { message: "The connection was cancelled.", code: "livekit_cancelled" };
      default:
        return { message: `LiveKit connection failed: ${e.message}`, code: "livekit_error" };
    }
  }
  const message = e instanceof Error ? e.message : String(e);
  return {
    message: `Could not connect to LiveKit at ${url}${message ? `: ${message}` : "."}`,
    code: "livekit_error",
  };
}

function mapAgentState(connection: ConnectionState, agentState: string): VoiceState {
  if (connection === ConnectionState.Disconnected) return "disconnected";
  if (connection !== ConnectionState.Connected) return "connecting";
  switch (agentState) {
    case "listening":
    case "thinking":
    case "speaking":
    case "idle":
    case "failed":
      return agentState;
    default:
      // initializing / connecting / pre-connect-buffering / disconnected (agent not in the room yet)
      return "initializing";
  }
}

const AGENT_WAIT_MS = 20_000;

/**
 * Lists audio inputs without ever prompting for permission (the browser only
 * reveals device labels after the user has granted the mic, i.e. after they
 * start a call; we re-enumerate then).
 */
function useMicDevices(room: Room) {
  const [list, setList] = useState<MediaDeviceInfo[]>([]);
  const [activeId, setActiveId] = useState("");
  const state = useConnectionState(room);

  useEffect(() => {
    let alive = true;
    const refresh = async () => {
      try {
        const all = await navigator.mediaDevices.enumerateDevices();
        if (!alive) return;
        setList(all.filter((d) => d.kind === "audioinput"));
        setActiveId(room.getActiveDevice("audioinput") ?? "");
      } catch {
        if (alive) setList([]);
      }
    };
    void refresh();
    navigator.mediaDevices?.addEventListener?.("devicechange", refresh);
    return () => {
      alive = false;
      navigator.mediaDevices?.removeEventListener?.("devicechange", refresh);
    };
  }, [room, state]);

  const select = useCallback(
    async (id: string) => {
      setActiveId(id);
      try {
        await room.switchActiveDevice("audioinput", id);
      } catch {
        /* surfaced through RoomEvent.MediaDevicesError */
      }
    },
    [room],
  );

  return { list, activeId, select };
}

// ------------------------------------------------------------------ live session

function LiveSession({ room, children }: { room: Room; children: ReactNode }) {
  const connection = useConnectionState(room);
  const assistant = useVoiceAssistant();
  const { microphoneTrack, isMicrophoneEnabled } = useLocalParticipant();
  const streams = useTranscriptions();
  const mics = useMicDevices(room);

  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<UiError | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [runId, setRunId] = useState<number | null>(null);
  const [traceState, setTraceState] = useState<string | null>(null);
  const [roomName, setRoomName] = useState<string | undefined>();
  const [hidden, setHidden] = useState<ReadonlySet<string>>(() => new Set());
  const runRef = useRef<number | null>(null);
  const calls = useRef(0);
  const trace = useTraceTranscript("voice", runId);

  const startRun = useCallback(() => {
    const id = inspectorStore.beginRun("voice", `Voice call ${++calls.current}`);
    runRef.current = id;
    setRunId(id);
    setTraceState(null);
    return id;
  }, []);

  // Trace events from the agent arrive on the data channel (topic omnivox.trace).
  useEffect(() => {
    const onData = (payload: Uint8Array, _p: unknown, _k: unknown, topic?: string) => {
      if (topic !== TRACE_TOPIC) return;
      inspectorStore.ingestRaw(payload, runRef.current ?? startRun(), "voice");
    };
    const onDisconnected = (reason?: DisconnectReason) => {
      setConnecting(false);
      if (reason != null && reason !== DisconnectReason.CLIENT_INITIATED) {
        setError({
          message: `The call ended: disconnected from the room (${DisconnectReason[reason] ?? reason}).`,
          code: "disconnected",
        });
      }
    };
    const onDeviceError = (e: Error) => setError({ message: micErrorMessage(e), code: "media_devices_error" });
    room.on(RoomEvent.DataReceived, onData);
    room.on(RoomEvent.Disconnected, onDisconnected);
    room.on(RoomEvent.MediaDevicesError, onDeviceError);
    return () => {
      room.off(RoomEvent.DataReceived, onData);
      room.off(RoomEvent.Disconnected, onDisconnected);
      room.off(RoomEvent.MediaDevicesError, onDeviceError);
    };
  }, [room, startRun]);

  // Latest agent_state from the trace, as a fallback for the participant attribute.
  useEffect(
    () =>
      inspectorStore.onEvent((e) => {
        if (e.origin === "voice" && e.run === runRef.current && e.source === "session" && e.type === "agent_state") {
          if (typeof e.data.state === "string") setTraceState(e.data.state);
        }
      }),
    [],
  );

  // The agent is dispatched when the room is created; flag it if it never shows up.
  const connected = connection === ConnectionState.Connected;
  const agentPresent = Boolean(assistant.agent);
  useEffect(() => {
    setWarning(null);
    if (!connected || agentPresent) return;
    const t = window.setTimeout(
      () => setWarning("The agent has not joined the room yet. Make sure the LiveKit agent worker is running."),
      AGENT_WAIT_MS,
    );
    return () => window.clearTimeout(t);
  }, [connected, agentPresent]);

  const connect = useCallback(async () => {
    if (room.state !== ConnectionState.Disconnected) return;
    setError(null);
    setWarning(null);
    setConnecting(true);

    let token: TokenResponse;
    try {
      token = await api.livekitToken({});
    } catch (e) {
      const ui = toUiError(e);
      setError({ ...ui, message: `Could not get a LiveKit token. ${ui.message}` });
      setConnecting(false);
      return;
    }

    startRun();
    trace.reset();
    setRoomName(token.room);
    try {
      await room.connect(token.url, token.token);
    } catch (e) {
      setError(connectionErrorMessage(e, token.url));
      setConnecting(false);
      await room.disconnect().catch(() => undefined);
      return;
    }
    try {
      await room.localParticipant.setMicrophoneEnabled(true);
    } catch (e) {
      setError({ message: micErrorMessage(e), code: "microphone" });
      await room.disconnect().catch(() => undefined);
    }
    setConnecting(false);
  }, [room, startRun, trace]);

  const disconnect = useCallback(async () => {
    await room.disconnect();
  }, [room]);

  const toggleMic = useCallback(() => {
    room.localParticipant.setMicrophoneEnabled(!room.localParticipant.isMicrophoneEnabled).catch((e: unknown) => {
      setError({ message: micErrorMessage(e), code: "microphone" });
    });
  }, [room]);

  // ---- levels
  const localTrack = microphoneTrack?.track;
  const micLevel = useLevelRef(localTrack && localTrack.kind === Track.Kind.Audio ? (localTrack as LocalAudioTrack) : undefined);
  const agentTrack = assistant.audioTrack?.publication?.track;
  const agentLevel = useLevelRef(
    agentTrack && agentTrack.kind === Track.Kind.Audio ? (agentTrack as RemoteAudioTrack) : undefined,
  );

  // ---- transcript: user from stt trace events, agent (and user as fallback) from LiveKit text streams
  const micSid = microphoneTrack?.trackSid;
  const localIdentity = room.localParticipant.identity;
  const transcript = useMemo<TranscriptEntry[]>(() => {
    const fromStreams: TranscriptEntry[] = [];
    for (const s of streams) {
      const attrs = s.streamInfo.attributes ?? {};
      const isUser =
        s.participantInfo.identity === localIdentity ||
        (micSid != null && attrs["lk.transcribed_track_id"] === micSid);
      if (isUser && trace.sawStt) continue; // already shown from richer trace events
      if (!s.text.trim()) continue;
      fromStreams.push({
        id: `s:${attrs["lk.segment_id"] ?? s.streamInfo.id}`,
        role: isUser ? "user" : "agent",
        text: s.text,
        final: attrs["lk.transcription_final"] !== "false",
        ts: s.streamInfo.timestamp,
      });
    }
    return [...trace.entries, ...fromStreams].filter((e) => !hidden.has(e.id)).sort((a, b) => a.ts - b.ts);
  }, [streams, trace.entries, trace.sawStt, micSid, localIdentity, hidden]);

  const agentDerived = mapAgentState(connection, assistant.state);
  const settled = agentDerived === "listening" || agentDerived === "thinking" || agentDerived === "speaking";
  const state: VoiceState =
    connected && !settled && (traceState === "listening" || traceState === "thinking" || traceState === "speaking")
      ? traceState
      : agentDerived;

  const clearTranscript = useCallback(() => setHidden(new Set(transcript.map((e) => e.id))), [transcript]);

  const session = useMemo<VoiceSession>(
    () => ({
      mode: "live",
      state: connecting && !connected ? "connecting" : state,
      connected,
      connecting,
      micEnabled: isMicrophoneEnabled,
      error,
      warning,
      connect,
      disconnect,
      toggleMic,
      transcript,
      clearTranscript,
      levels: { mic: micLevel, agent: agentLevel },
      devices: {
        list: mics.list
          .filter((d) => d.deviceId)
          .map((d, i) => ({ id: d.deviceId, label: d.label || `Microphone ${i + 1}` })),
        activeId: mics.activeId,
        select: (id) => void mics.select(id),
      },
      roomName,
    }),
    [
      connecting,
      connected,
      state,
      isMicrophoneEnabled,
      error,
      warning,
      connect,
      disconnect,
      toggleMic,
      transcript,
      clearTranscript,
      micLevel,
      agentLevel,
      mics,
      roomName,
    ],
  );

  return <LiveCtx.Provider value={session}>{children}</LiveCtx.Provider>;
}
