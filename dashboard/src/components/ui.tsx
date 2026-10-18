import { X } from "lucide-react";
import React, { useLayoutEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";
export function Badge({ value }: { value: string }) {
  return (
    <span
      className={
        "badge " +
        ([
          "published",
          "approved",
          "valid",
          "completed",
          "resolved",
          "in-progress",
        ].includes(value)
          ? "green"
          : ["failed", "revoked", "cancelled", "dispatch_unknown"].includes(
                value,
              )
            ? "red"
            : ["running", "ringing", "pending"].includes(value)
              ? "blue"
              : "neutral")
      }
    >
      <i />
      {value.replaceAll("_", " ").replaceAll("-", " ")}
    </span>
  );
}
export function Button({
  children,
  onClick,
  kind = "",
  disabled = false,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  kind?: string;
  disabled?: boolean;
  type?: "button" | "submit";
}) {
  return (
    <button
      type={type}
      disabled={disabled}
      className={"button " + kind}
      onClick={onClick}
    >
      {children}
    </button>
  );
}
export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  const id = React.useId();
  const control =
    React.isValidElement(children) &&
    typeof children.type === "string" &&
    ["input", "textarea", "select"].includes(children.type)
      ? React.cloneElement(children as React.ReactElement<any>, {
          "aria-label": label,
          "aria-describedby": hint ? id : undefined,
        })
      : children;
  return (
    <label className="field">
      <span>{label}</span>
      {control}
      {hint && <small id={id}>{hint}</small>}
    </label>
  );
}
export function Empty({
  title,
  children,
  action,
}: {
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      <p>{children}</p>
      {action}
    </div>
  );
}
export function Modal({
  title,
  subtitle,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const panel = React.useRef<HTMLDialogElement>(null);
  const titleId = React.useId();
  const subtitleId = React.useId();
  useLayoutEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const dialog = panel.current!;
    // Native top-layer dialogs provide background inertness and nested focus containment.
    dialog.showModal();
    return () => {
      dialog.close();
      document.body.style.overflow = oldOverflow;
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  return createPortal(
    <dialog
      ref={panel}
      className="overlay modal-layer"
      aria-labelledby={titleId}
      aria-describedby={subtitle ? subtitleId : undefined}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section className={"modal " + (wide ? "wide" : "")}>
        <header>
          <div>
            <h2 id={titleId}>{title}</h2>
            {subtitle && <p id={subtitleId}>{subtitle}</p>}
          </div>
          <button
            className="icon-button"
            aria-label="Close dialog"
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </header>
        {children}
      </section>
    </dialog>,
    document.body,
  );
}
export function TimezoneSelect({
  zones,
  ...props
}: { zones: string[] } & React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select aria-label="Timezone" required {...props}>
      {zones.map((zone) => (
        <option key={zone} value={zone}>
          {zone.replaceAll("_", " ")}
        </option>
      ))}
    </select>
  );
}

/** Layout placeholder shared by route and resource loading states. */
export function Skeleton({ label = "Loading" }: { label?: string }) {
  return (
    <div className="skeleton-panel card" role="status" aria-label={label}>
      <span className="sr-only">{label}</span>
      <div aria-hidden="true">
        <div className="skeleton-line skeleton-title" />
        {[0, 1, 2, 3].map((row) => (
          <div className="skeleton-row" key={row}>
            <span className="skeleton-line" />
            <span className="skeleton-line" />
          </div>
        ))}
      </div>
    </div>
  );
}
