import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { AlertCircle, CheckCircle2, X } from "lucide-react";
import { ApiError } from "../api/client";

interface ToastItem {
  id: number;
  tone: "success" | "error";
  title: string;
  detail?: string;
}

interface ToastApi {
  success: (title: string, detail?: string) => void;
  error: (title: string, detail?: string) => void;
  /** Error toast whose detail comes from an API error. */
  apiError: (title: string, error: unknown) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => setItems((all) => all.filter((t) => t.id !== id)), []);

  const push = useCallback(
    (tone: ToastItem["tone"], title: string, detail?: string) => {
      const id = nextId.current++;
      setItems((all) => [...all.slice(-3), { id, tone, title, detail }]);
      setTimeout(() => dismiss(id), tone === "error" ? 7000 : 4000);
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      success: (title, detail) => push("success", title, detail),
      error: (title, detail) => push("error", title, detail),
      apiError: (title, error) =>
        push("error", title, error instanceof ApiError ? error.detail : (error as Error)?.message),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      {createPortal(
        <div className="toast-stack" aria-live="polite">
          {items.map((t) => (
            <div key={t.id} className="toast" role={t.tone === "error" ? "alert" : "status"}>
              <span className={`toast__icon--${t.tone}`}>
                {t.tone === "success" ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
              </span>
              <div className="toast__body">
                <div className="toast__title">{t.title}</div>
                {t.detail && <div className="toast__detail">{t.detail}</div>}
              </div>
              <button aria-label="Dismiss" onClick={() => dismiss(t.id)}>
                <X size={16} />
              </button>
            </div>
          ))}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside ToastProvider");
  return ctx;
}
