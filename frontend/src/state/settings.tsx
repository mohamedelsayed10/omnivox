import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { readStorage, STORAGE_KEYS, writeStorage } from "../lib/storage";

export type ThemeMode = "system" | "dark" | "light";
export type Theme = "dark" | "light";

interface Settings {
  apiKey: string;
  setApiKey: (key: string) => void;
  /** Bumps whenever the key changes so data hooks can refetch. */
  keyVersion: number;
  themeMode: ThemeMode;
  setThemeMode: (mode: ThemeMode) => void;
  /** The theme actually applied (system resolved). */
  theme: Theme;
  toggleTheme: () => void;
}

const Ctx = createContext<Settings | null>(null);

function systemTheme(): Theme {
  // Dark is the default when the OS expresses no preference.
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function initialMode(): ThemeMode {
  const q = new URLSearchParams(window.location.search).get("theme");
  if (q === "light" || q === "dark") return q;
  const v = readStorage(STORAGE_KEYS.theme);
  return v === "dark" || v === "light" || v === "system" ? v : "system";
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [apiKey, setKey] = useState(() => readStorage(STORAGE_KEYS.apiKey) ?? "");
  const [keyVersion, setKeyVersion] = useState(0);
  const [themeMode, setMode] = useState<ThemeMode>(initialMode);
  const [sys, setSys] = useState<Theme>(systemTheme);

  useEffect(() => {
    const mql = window.matchMedia("(prefers-color-scheme: light)");
    const on = () => setSys(mql.matches ? "light" : "dark");
    mql.addEventListener("change", on);
    return () => mql.removeEventListener("change", on);
  }, []);

  const theme: Theme = themeMode === "system" ? sys : themeMode;

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", theme === "dark" ? "#0a0c12" : "#f3f4f9");
  }, [theme]);

  const setApiKey = useCallback((key: string) => {
    const trimmed = key.trim();
    writeStorage(STORAGE_KEYS.apiKey, trimmed || null);
    setKey(trimmed);
    setKeyVersion((v) => v + 1);
  }, []);

  const setThemeMode = useCallback((mode: ThemeMode) => {
    writeStorage(STORAGE_KEYS.theme, mode);
    setMode(mode);
  }, []);

  const toggleTheme = useCallback(() => setThemeMode(theme === "dark" ? "light" : "dark"), [theme, setThemeMode]);

  const value = useMemo<Settings>(
    () => ({ apiKey, setApiKey, keyVersion, themeMode, setThemeMode, theme, toggleTheme }),
    [apiKey, setApiKey, keyVersion, themeMode, setThemeMode, theme, toggleTheme],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSettings(): Settings {
  const v = useContext(Ctx);
  if (!v) throw new Error("useSettings outside SettingsProvider");
  return v;
}
