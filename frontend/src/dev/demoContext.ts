import { createContext, useContext } from "react";
import type { VoiceSession } from "../state/voiceTypes";

/**
 * Hook point for the dev-only "Simulate call" feature. In production builds no
 * provider is mounted, so `useDemo()` is null and the UI never offers it.
 */
export interface DemoApi {
  active: boolean;
  starting: boolean;
  start: () => void;
  stop: () => void;
  /** A VoiceSession driven by replayed events instead of LiveKit. */
  session: VoiceSession;
}

export const DemoContext = createContext<DemoApi | null>(null);

export function useDemo(): DemoApi | null {
  return useContext(DemoContext);
}
