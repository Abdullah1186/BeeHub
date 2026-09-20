import { useEffect, useState } from "react";
import type { ReactNode, ButtonHTMLAttributes, InputHTMLAttributes } from "react";

/* Shared primitives. Everything here reads from the CSS custom properties in
   index.css, so light/dark is handled by the tokens rather than by each
   component carrying two sets of classes. */

// ---------------------------------------------------------------- Logo

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true">
      {/* A hexagon — honeycomb, for "hub". */}
      <path
        d="M16 2.5 28 9.25v13.5L16 29.5 4 22.75V9.25z"
        fill="var(--accent)"
        fillOpacity="0.16"
        stroke="var(--accent)"
        strokeWidth="1.75"
        strokeLinejoin="round"
      />
      {/* An alif inside: the first letter, and a vertical stroke reads as a
          bookmark at this size. */}
      <path
        d="M16 10v9.5c0 1.6 1 2.5 2.6 2.5"
        stroke="var(--accent-text)"
        strokeWidth="2.25"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  );
}

export function Wordmark({ size = 28 }: { size?: number }) {
  return (
    <span className="inline-flex items-center gap-2">
      <Logo size={size} />
      <span
        className="font-semibold tracking-tight"
        style={{ fontSize: size * 0.68, color: "var(--text)" }}
      >
        Bee<span style={{ color: "var(--accent-text)" }}>Hub</span>
      </span>
    </span>
  );
}

// ---------------------------------------------------------------- Button

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
  icon?: ReactNode;
};

export function Button({
  variant = "primary",
  size = "md",
  loading,
  icon,
  children,
  className = "",
  disabled,
  ...rest
}: ButtonProps) {
  const sizes = {
    sm: "px-3 py-1.5 text-sm gap-1.5",
    md: "px-4 py-2.5 text-sm gap-2",
    lg: "px-5 py-3 text-base gap-2",
  }[size];

  const variants: Record<string, string> = {
    primary: "text-[var(--accent-fg)] bg-[var(--accent)] hover:brightness-95 shadow-[var(--shadow-sm)]",
    secondary:
      "text-[var(--text)] bg-[var(--surface)] border border-[var(--border)] hover:bg-[var(--surface-alt)]",
    ghost: "text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-alt)]",
    danger: "text-[var(--bad-text)] bg-[var(--bad-bg)] hover:brightness-95",
  };

  return (
    <button
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center rounded-lg font-medium
                  transition-[filter,background-color,transform] active:scale-[0.98]
                  disabled:opacity-50 disabled:pointer-events-none
                  ${sizes} ${variants[variant]} ${className}`}
      {...rest}
    >
      {loading ? <Spinner /> : icon}
      {children}
    </button>
  );
}

export function Spinner({ size = 14 }: { size?: number }) {
  return (
    <svg
      className="animate-spin"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.25" />
      <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

// ---------------------------------------------------------------- Surfaces

export function Card({
  children,
  className = "",
  interactive,
}: {
  children: ReactNode;
  className?: string;
  interactive?: boolean;
}) {
  return (
    <div
      className={`rounded-[var(--radius-card)] border border-[var(--border)]
                  bg-[var(--surface)] shadow-[var(--shadow-sm)]
                  ${interactive ? "transition-shadow hover:shadow-[var(--shadow-md)]" : ""}
                  ${className}`}
    >
      {children}
    </div>
  );
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "ok" | "warn" | "bad" | "accent";
}) {
  const tones: Record<string, string> = {
    neutral: "bg-[var(--surface-alt)] text-[var(--text-muted)]",
    ok: "bg-[var(--ok-bg)] text-[var(--ok-text)]",
    warn: "bg-[var(--warn-bg)] text-[var(--warn-text)]",
    bad: "bg-[var(--bad-bg)] text-[var(--bad-text)]",
    accent: "bg-[var(--accent-soft)] text-[var(--accent-text)]",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5
                  text-xs font-medium whitespace-nowrap ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

export function Input({ className = "", ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`w-full rounded-lg border border-[var(--border)] bg-[var(--surface)]
                  px-3 py-2.5 text-sm text-[var(--text)]
                  placeholder:text-[var(--text-subtle)]
                  focus:border-[var(--accent)] focus:outline-none
                  focus:ring-2 focus:ring-[var(--accent)]/20 ${className}`}
      {...rest}
    />
  );
}

// ---------------------------------------------------------------- Loading

/** Skeleton placeholder. Shaped like the content it replaces, so the layout
 *  does not jump when the real thing arrives. */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton rounded-md ${className}`} />;
}

export function SkeletonCard() {
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 space-y-2.5">
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-3.5 w-1/3" />
        </div>
        <Skeleton className="h-6 w-20 rounded-full" />
      </div>
      <Skeleton className="mt-5 h-9 w-full" />
    </Card>
  );
}

/** Determinate or indeterminate progress. The worker gives no percentage, so
 *  `value` is omitted while a job is queued and the bar animates instead. */
export function Progress({ value, label }: { value?: number; label?: string }) {
  const indeterminate = value === undefined;
  return (
    <div className="space-y-1.5">
      {label && (
        <div className="flex justify-between text-xs text-[var(--text-muted)]">
          <span>{label}</span>
          {!indeterminate && <span>{Math.round(value * 100)}%</span>}
        </div>
      )}
      <div className="h-1.5 overflow-hidden rounded-full bg-[var(--surface-alt)]">
        <div
          className={`h-full rounded-full bg-[var(--accent)] ${
            indeterminate ? "w-1/3 animate-[shimmer_1.4s_ease-in-out_infinite]" : "transition-[width] duration-500"
          }`}
          style={indeterminate ? undefined : { width: `${value * 100}%` }}
        />
      </div>
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon?: ReactNode;
  title: string;
  body?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-[var(--radius-card)]
                    border border-dashed border-[var(--border)] px-6 py-12 text-center">
      {icon && <div className="text-[var(--text-subtle)]">{icon}</div>}
      <div>
        <p className="font-medium text-[var(--text)]">{title}</p>
        {body && <p className="mt-1 text-sm text-[var(--text-muted)]">{body}</p>}
      </div>
      {action}
    </div>
  );
}

/** A score dial. Communicates a proportion faster than a number alone. */
export function ScoreRing({
  value,
  label,
  size = 84,
}: {
  value: number;
  label: string;
  size?: number;
}) {
  const r = (size - 10) / 2;
  const circumference = 2 * Math.PI * r;
  const tone =
    value >= 0.8 ? "var(--ok-text)" : value >= 0.5 ? "var(--accent)" : "var(--bad-text)";

  return (
    <div className="flex flex-col items-center gap-1.5">
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90">
          <circle
            cx={size / 2} cy={size / 2} r={r}
            stroke="var(--surface-alt)" strokeWidth="6" fill="none"
          />
          <circle
            cx={size / 2} cy={size / 2} r={r}
            stroke={tone} strokeWidth="6" fill="none" strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={circumference * (1 - value)}
            style={{ transition: "stroke-dashoffset 0.7s ease-out" }}
          />
        </svg>
        <span
          className="absolute inset-0 flex items-center justify-center text-lg font-semibold"
          style={{ color: tone }}
        >
          {Math.round(value * 100)}%
        </span>
      </div>
      <span className="text-xs text-[var(--text-muted)]">{label}</span>
    </div>
  );
}


// ---------------------------------------------------------------- Confirm

/** A destructive action that asks first, inline.
 *
 *  Inline rather than a modal: deleting one row in a list is a small decision,
 *  and a dialog that steals focus is heavier than the action deserves. The
 *  confirm state names the consequence, because "Delete" alone does not say
 *  what survives. */
export function ConfirmButton({
  onConfirm,
  label = "Delete",
  confirmLabel = "Confirm",
  question,
  busy,
}: {
  onConfirm: () => void;
  label?: string;
  confirmLabel?: string;
  question?: string;
  busy?: boolean;
}) {
  const [armed, setArmed] = useState(false);

  // Disarm after a few seconds, so a stray click does not leave a live
  // delete button sitting under the cursor.
  useEffect(() => {
    if (!armed) return;
    const timer = setTimeout(() => setArmed(false), 5000);
    return () => clearTimeout(timer);
  }, [armed]);

  if (!armed) {
    return (
      <Button variant="ghost" size="sm" onClick={() => setArmed(true)}>
        {label}
      </Button>
    );
  }

  return (
    <div className="flex items-center gap-2">
      {question && (
        <span className="text-xs text-[var(--text-muted)]">{question}</span>
      )}
      <Button variant="danger" size="sm" loading={busy} onClick={onConfirm}>
        {confirmLabel}
      </Button>
      <Button variant="ghost" size="sm" onClick={() => setArmed(false)}>
        Cancel
      </Button>
    </div>
  );
}
