import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { readStorage, STORAGE_KEYS, writeStorage } from "../lib/storage";

export type View = "voice" | "chat" | "knowledge";
export const VIEWS: readonly View[] = ["voice", "chat", "knowledge"];

export const INSPECTOR_MIN = 320;
export const INSPECTOR_MAX = 760;
const INSPECTOR_DEFAULT = 440;

/** Below this width the Inspector is an overlay drawer instead of a docked column. */
export const DOCK_QUERY = "(min-width: 1060px)";
export const MOBILE_QUERY = "(max-width: 720px)";

interface Layout {
  view: View;
  navigate: (v: View) => void;
  docked: boolean;
  mobile: boolean;
  /** Whether the Inspector is visible in the current mode (docked column or drawer). */
  inspectorVisible: boolean;
  toggleInspector: () => void;
  closeInspector: () => void;
  inspectorWidth: number;
  setInspectorWidth: (w: number) => void;
}

const Ctx = createContext<Layout | null>(null);

function viewFromHash(): View {
  const h = window.location.hash.replace(/^#\/?/, "");
  return (VIEWS as readonly string[]).includes(h) ? (h as View) : "voice";
}

export function clampWidth(w: number): number {
  const max = Math.min(INSPECTOR_MAX, Math.round(window.innerWidth * 0.62));
  return Math.max(INSPECTOR_MIN, Math.min(max, Math.round(w)));
}

export function LayoutProvider({ children }: { children: ReactNode }) {
  const [view, setView] = useState<View>(viewFromHash);
  const docked = useMediaQuery(DOCK_QUERY);
  const mobile = useMediaQuery(MOBILE_QUERY);
  const [dockOpen, setDockOpen] = useState(() => readStorage(STORAGE_KEYS.inspectorOpen) !== "0");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [width, setWidth] = useState(() => {
    const stored = Number(readStorage(STORAGE_KEYS.inspectorWidth));
    return Number.isFinite(stored) && stored > 0 ? stored : INSPECTOR_DEFAULT;
  });

  useEffect(() => {
    const on = () => setView(viewFromHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  const navigate = useCallback((v: View) => {
    window.location.hash = `/${v}`;
    setView(v);
  }, []);

  const toggleInspector = useCallback(() => {
    if (docked) {
      setDockOpen((o) => {
        writeStorage(STORAGE_KEYS.inspectorOpen, o ? "0" : "1");
        return !o;
      });
    } else setDrawerOpen((o) => !o);
  }, [docked]);

  const closeInspector = useCallback(() => {
    if (docked) {
      setDockOpen(false);
      writeStorage(STORAGE_KEYS.inspectorOpen, "0");
    } else setDrawerOpen(false);
  }, [docked]);

  // Leaving drawer mode (resize) should not leave a stale drawer open.
  useEffect(() => {
    if (docked) setDrawerOpen(false);
  }, [docked]);

  const setInspectorWidth = useCallback((w: number) => {
    const next = clampWidth(w);
    setWidth(next);
    writeStorage(STORAGE_KEYS.inspectorWidth, String(next));
  }, []);

  const value = useMemo<Layout>(
    () => ({
      view,
      navigate,
      docked,
      mobile,
      inspectorVisible: docked ? dockOpen : drawerOpen,
      toggleInspector,
      closeInspector,
      inspectorWidth: clampWidth(width),
      setInspectorWidth,
    }),
    [view, navigate, docked, mobile, dockOpen, drawerOpen, toggleInspector, closeInspector, width, setInspectorWidth],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useLayout(): Layout {
  const v = useContext(Ctx);
  if (!v) throw new Error("useLayout outside LayoutProvider");
  return v;
}
