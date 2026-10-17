import { useEffect, useRef, type FormEvent, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { Button } from "./Button";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

// Open dialogs, innermost last; only that one reacts to keys.
const stack: object[] = [];

/** Esc closes, Tab stays inside the dialog, focus returns to where it was on close. */
function useDialog(ref: RefObject<HTMLElement | null>, onClose: () => void) {
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const token = {};
    stack.push(token);
    const opener = document.activeElement as HTMLElement | null;
    const node = ref.current;
    if (node && !node.contains(document.activeElement)) {
      const first = node.querySelector<HTMLElement>("[autofocus]") ?? node.querySelector<HTMLElement>(FOCUSABLE);
      (first ?? node).focus();
    }
    const onKey = (e: KeyboardEvent) => {
      if (stack[stack.length - 1] !== token) return;
      if (e.key === "Escape") {
        e.stopPropagation();
        closeRef.current();
        return;
      }
      if (e.key !== "Tab" || !ref.current) return;
      const items = [...ref.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.offsetParent !== null);
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      stack.splice(stack.indexOf(token), 1);
      document.body.style.overflow = previous;
      opener?.focus?.();
    };
  }, [ref]);
}

interface ModalProps {
  title: ReactNode;
  description?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
  /** Render the body and footer inside a <form> so Enter submits. */
  onSubmit?: () => void;
}

export function Modal({ title, description, onClose, children, footer, wide, onSubmit }: ModalProps) {
  const ref = useRef<HTMLDivElement>(null);
  useDialog(ref, onClose);
  const inner = (
    <>
      <div className="modal__body">{children}</div>
      {footer && <div className="modal__footer">{footer}</div>}
    </>
  );
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit?.();
  };
  return createPortal(
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} tabIndex={-1} className={`modal ${wide ? "modal--wide" : ""}`} role="dialog" aria-modal="true">
        <div className="modal__header">
          <div style={{ flex: 1 }}>
            <h2>{title}</h2>
            {description && <p>{description}</p>}
          </div>
          <Button variant="ghost" size="sm" aria-label="Close" icon={<X size={16} />} onClick={onClose} />
        </div>
        {onSubmit ? (
          <form onSubmit={submit} noValidate>
            {inner}
          </form>
        ) : (
          inner
        )}
      </div>
    </div>,
    document.body,
  );
}

interface DrawerProps {
  title: ReactNode;
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
}

export function Drawer({ title, subtitle, onClose, children }: DrawerProps) {
  const ref = useRef<HTMLElement>(null);
  useDialog(ref, onClose);
  return createPortal(
    <>
      <div className="drawer-overlay" onClick={onClose} />
      <aside ref={ref} tabIndex={-1} className="drawer" role="dialog" aria-modal="true">
        <div className="drawer__header">
          <div style={{ flex: 1, minWidth: 0 }}>
            <h2 style={{ fontSize: 17 }}>{title}</h2>
            {subtitle && <div style={{ marginTop: 6 }}>{subtitle}</div>}
          </div>
          <Button variant="ghost" size="sm" aria-label="Close" icon={<X size={16} />} onClick={onClose} />
        </div>
        <div className="drawer__body">{children}</div>
      </aside>
    </>,
    document.body,
  );
}

interface ConfirmProps {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  loading?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

export function ConfirmDialog({ title, children, confirmLabel, danger, loading, onConfirm, onClose }: ConfirmProps) {
  return (
    <Modal
      title={title}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant={danger ? "danger" : "primary"} loading={loading} onClick={onConfirm} autoFocus>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="stack-sm">{children}</div>
    </Modal>
  );
}
