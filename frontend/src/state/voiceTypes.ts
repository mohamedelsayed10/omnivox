import type { MutableRefObject } from "react";
import type { UiError } from "../components/ErrorBanner";

export type VoiceState =
  | "disconnected"
  | "connecting"
  | "initializing"
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "failed";

export interface TranscriptEntry {
  id: string;
  role: "user" | "agent";
  text: string;
  /** false while the text is still being revised (interim STT / streaming TTS text). */
  final: boolean;
  /** Epoch ms, used only for ordering. */
  ts: number;
}

export interface MicDevice {
  id: string;
  label: string;
}

/** Everything the Voice view needs. Implemented by the live LiveKit session and by the dev-only demo. */
export interface VoiceSession {
  mode: "live" | "demo";
  state: VoiceState;
  /** Joined the room (live) or running the replay (demo). */
  connected: boolean;
  connecting: boolean;
  micEnabled: boolean;
  error: UiError | null;
  /** Non-fatal hint, e.g. "the agent has not joined yet". */
  warning: string | null;
  connect: () => Promise<void>;
  disconnect: () => Promise<void> | void;
  toggleMic: () => void;
  transcript: TranscriptEntry[];
  clearTranscript: () => void;
  /** 0..1 live audio levels, read by the orb each animation frame (no re-render). */
  levels: { mic: MutableRefObject<number>; agent: MutableRefObject<number> };
  devices: { list: MicDevice[]; activeId: string; select: (id: string) => void };
  roomName?: string;
}
