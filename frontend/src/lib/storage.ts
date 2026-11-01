/** localStorage that never throws (private windows, blocked storage, SSR). */

export function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStorage(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: the setting simply won't persist */
  }
}

export const STORAGE_KEYS = {
  apiKey: "omnivox.apiKey",
  theme: "omnivox.theme",
  inspectorOpen: "omnivox.inspector.open",
  inspectorWidth: "omnivox.inspector.width",
  sessionId: "omnivox.chat.sessionId",
  streamTokens: "omnivox.chat.stream",
  autoScroll: "omnivox.inspector.autoscroll",
} as const;
