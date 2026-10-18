import { AudioLines, X } from "lucide-react";
import React, { useEffect, type ReactNode } from "react";
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
      <div className="empty-symbol">
        <AudioLines size={28} />
      </div>
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
  const panel = React.useRef<HTMLElement>(null);
  const close = React.useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusable = () =>
      Array.from(
        panel.current?.querySelectorAll<HTMLElement>(
          "button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], iframe",
        ) || [],
      );
    focusable()[0]?.focus();
    const listener = (event: KeyboardEvent) => {
      if (event.key === "Escape") close.current();
      if (event.key === "Tab") {
        const elements = focusable();
        const index = elements.indexOf(document.activeElement as HTMLElement);
        if (
          index < 0 ||
          (!event.shiftKey && index === elements.length - 1) ||
          (event.shiftKey && index === 0)
        ) {
          event.preventDefault();
          (event.shiftKey ? elements.at(-1) : elements[0])?.focus();
        }
      }
    };
    window.addEventListener("keydown", listener);
    return () => {
      window.removeEventListener("keydown", listener);
      document.body.style.overflow = oldOverflow;
      previous?.focus();
    };
  }, []);
  return (
    <div
      className="overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={"modal " + (wide ? "wide" : "")}
      >
        <header>
          <div>
            <h2>{title}</h2>
            {subtitle && <p>{subtitle}</p>}
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
    </div>
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
