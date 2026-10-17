import { cloneElement, isValidElement, useId, type ReactElement, type ReactNode } from "react";

type ControlProps = { id?: string; "aria-invalid"?: boolean; "aria-describedby"?: string };

interface FieldProps {
  label: ReactNode;
  hint?: ReactNode;
  error?: string;
  optional?: boolean;
  className?: string;
  /** Id of the input when it is wrapped (e.g. in an input group) rather than the direct child. */
  controlId?: string;
  children: ReactElement<ControlProps>;
}

const NATIVE_CONTROLS = new Set(["input", "select", "textarea"]);

/** Label + control + hint/error. Wires up ids and aria attributes on a direct input child. */
export function Field({ label, hint, error, optional, className, controlId, children }: FieldProps) {
  const generated = useId();
  const noteId = `${generated}-note`;
  const isControl = isValidElement(children) && typeof children.type === "string" && NATIVE_CONTROLS.has(children.type);
  const inputId = controlId ?? children.props.id ?? generated;
  const control = isControl
    ? cloneElement(children, {
        id: inputId,
        "aria-invalid": error ? true : undefined,
        "aria-describedby": error || hint ? noteId : undefined,
      })
    : children;
  return (
    <div className={`field ${className ?? ""}`}>
      <label className="field__label" htmlFor={isControl || controlId ? inputId : undefined}>
        {label}
        {optional && <span className="optional">optional</span>}
      </label>
      {control}
      {error ? (
        <span className="field__error" id={noteId}>
          {error}
        </span>
      ) : (
        hint && (
          <span className="field__hint" id={noteId}>
            {hint}
          </span>
        )
      )}
    </div>
  );
}

export function Switch({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <label className="switch">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        aria-label={label}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="switch__track" />
    </label>
  );
}
