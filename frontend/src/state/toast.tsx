import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import { describeError } from "../api/client";

type ToastKind = "ok" | "err" | "info";
interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
  requestId?: string;
}

interface ToastApi {
  success: (message: string) => void;
  info: (message: string) => void;
  /** Show any thrown value, with its request_id when it has one. */
  error: (e: unknown, prefix?: string) => void;
}

const Ctx = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => setItems((l) => l.filter((t) => t.id !== id)), []);
  const push = useCallback(
    (t: Omit<ToastItem, "id">, ms: number) => {
      const id = nextId.current++;
      setItems((l) => [...l.slice(-3), { ...t, id }]);
      window.setTimeout(() => dismiss(id), ms);
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      success: (message) => push({ kind: "ok", message }, 3500),
      info: (message) => push({ kind: "info", message }, 4000),
      error: (e, prefix) => {
        const d = describeError(e);
        push({ kind: "err", message: prefix ? `${prefix}: ${d.message}` : d.message, requestId: d.requestId }, 8000);
      },
    }),
    [push],
  );

  return (
    <Ctx.Provider value={api}>
      {children}
      <div className="toasts" role="region" aria-label="Notifications" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            {t.kind === "err" ? (
              <AlertCircle size={18} color="var(--err)" />
            ) : t.kind === "ok" ? (
              <CheckCircle2 size={18} color="var(--ok)" />
            ) : (
              <Info size={18} color="var(--accent)" />
            )}
            <div className="toast-body">
              {t.message}
              {t.requestId && <small>request_id: {t.requestId}</small>}
            </div>
            <button className="btn btn-ghost btn-icon btn-sm" aria-label="Dismiss" onClick={() => dismiss(t.id)}>
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToast(): ToastApi {
  const v = useContext(Ctx);
  if (!v) throw new Error("useToast outside ToastProvider");
  return v;
}
