import { AlertTriangle, RefreshCw, X } from "lucide-react";
import { describeError } from "../api/client";
import { CopyButton } from "./CopyButton";

export interface UiError {
  message: string;
  code?: string;
  requestId?: string;
}

export function toUiError(e: unknown): UiError {
  return describeError(e);
}

/** Error with its machine code and request_id, so a failure can be traced in backend logs. */
export function ErrorBanner({
  error,
  title,
  onRetry,
  onDismiss,
  tone = "error",
}: {
  error: UiError;
  title?: string;
  onRetry?: () => void;
  onDismiss?: () => void;
  tone?: "error" | "warn";
}) {
  return (
    <div className={`banner${tone === "warn" ? " warn" : ""}`} role="alert">
      <AlertTriangle size={18} aria-hidden />
      <div className="banner-body">
        {title && <div className="banner-title">{title}</div>}
        <div className={title ? "" : "banner-title"}>{error.message}</div>
        {(error.code || error.requestId) && (
          <div className="banner-meta">
            {error.code && (
              <span>
                code <span className="mono">{error.code}</span>
              </span>
            )}
            {error.requestId && (
              <span style={{ display: "inline-flex", alignItems: "center", gap: 2 }}>
                request_id <span className="mono">{error.requestId}</span>
                <CopyButton text={error.requestId} label="Copy request id" />
              </span>
            )}
          </div>
        )}
      </div>
      {onRetry && (
        <button className="btn btn-sm" onClick={onRetry}>
          <RefreshCw size={14} /> Retry
        </button>
      )}
      {onDismiss && (
        <button className="btn btn-ghost btn-icon btn-sm" aria-label="Dismiss error" onClick={onDismiss}>
          <X size={14} />
        </button>
      )}
    </div>
  );
}
