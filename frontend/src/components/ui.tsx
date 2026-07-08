/** Reusable UI primitives — shadcn-inspired, Tailwind-styled, fully typed. */
import { ReactNode, InputHTMLAttributes, ButtonHTMLAttributes, CSSProperties, useState } from "react";
import { Eye, EyeOff, ChevronDown } from "lucide-react";

export function cn(...parts: (string | false | undefined | null)[]): string {
  return parts.filter(Boolean).join(" ");
}

// ---------------------------------------------------------------- WiggleText
/** Splits text into per-letter spans that wiggle in a staggered wave on hover. */
export function WiggleText({ children, className }: { children: string; className?: string }) {
  return (
    <span className={cn("wt-wiggle-text", className)}>
      {[...children].map((ch, i) => (
        <span key={i} className="wt-wiggle-char" style={{ "--wt-i": i } as CSSProperties}>
          {ch === " " ? " " : ch}
        </span>
      ))}
    </span>
  );
}

// ------------------------------------------------------------------- Button
type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
};
export function Button({ variant = "secondary", size = "md", className, ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-xl font-medium transition-all duration-150",
        "disabled:opacity-50 disabled:pointer-events-none active:scale-[0.98]",
        size === "sm" && "h-8 px-3 text-xs",
        size === "md" && "h-9 px-4 text-sm",
        size === "lg" && "h-11 px-6 text-base",
        variant === "primary" && "bg-accent text-white hover:brightness-110 shadow-lg shadow-accent/25",
        variant === "secondary" && "bg-elevated border border-border hover:bg-border/60",
        variant === "ghost" && "hover:bg-elevated",
        variant === "danger" && "bg-red-500/15 text-red-400 border border-red-500/30 hover:bg-red-500/25",
        className,
      )}
      {...props}
    />
  );
}

// --------------------------------------------------------------------- Card
export function Card({ children, className, onClick }: { children: ReactNode; className?: string; onClick?: () => void }) {
  return (
    <div
      onClick={onClick}
      className={cn(
        "bg-surface border border-border rounded-2xl p-5",
        onClick && "cursor-pointer hover:border-accent/50 transition-colors duration-150",
        className,
      )}
    >
      {children}
    </div>
  );
}

// ------------------------------------------------------------------- Toggle
export function Toggle({ checked, onChange, label, description, disabled }: {
  checked: boolean; onChange: (v: boolean) => void; label: string; description?: string; disabled?: boolean;
}) {
  return (
    <label className={cn("flex items-center justify-between gap-4 py-2.5", disabled && "opacity-50")}>
      <div className="min-w-0">
        <div className="text-sm font-medium">{label}</div>
        {description && <div className="text-xs text-muted mt-0.5">{description}</div>}
      </div>
      <button
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative w-10 h-[22px] rounded-full transition-colors duration-200 shrink-0",
          checked ? "bg-accent" : "bg-border",
        )}
      >
        <span className={cn(
          "absolute top-[3px] w-4 h-4 rounded-full bg-white transition-all duration-200",
          checked ? "left-[21px]" : "left-[3px]",
        )} />
      </button>
    </label>
  );
}

// ------------------------------------------------------------------- Select
export function Select({ value, onChange, options, label, className }: {
  value: string; onChange: (v: string) => void;
  options: { value: string; label: string }[]; label?: string; className?: string;
}) {
  return (
    <div className={className}>
      {label && <div className="text-xs text-muted mb-1.5">{label}</div>}
      <div className="relative">
        <select
          value={value}
          aria-label={label}
          onChange={(e) => onChange(e.target.value)}
          className="w-full h-9 appearance-none rounded-xl bg-elevated border border-border px-3 pr-9 text-sm focus:border-accent transition-colors"
        >
          {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted pointer-events-none" />
      </div>
    </div>
  );
}

// -------------------------------------------------------------------- Input
type InputProps = InputHTMLAttributes<HTMLInputElement> & { label?: string };
export function Input({ label, className, ...props }: InputProps) {
  return (
    <div className={className}>
      {label && <div className="text-xs text-muted mb-1.5">{label}</div>}
      <input
        className="w-full h-9 rounded-xl bg-elevated border border-border px-3 text-sm placeholder:text-muted/60 focus:border-accent transition-colors"
        {...props}
      />
    </div>
  );
}

export function SecretInput({ label, value, onChange, placeholder }: {
  label?: string; value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <div>
      {label && <div className="text-xs text-muted mb-1.5">{label}</div>}
      <div className="relative">
        <input
          type={show ? "text" : "password"}
          value={value}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
          autoComplete="off"
          className="w-full h-9 rounded-xl bg-elevated border border-border px-3 pr-10 text-sm placeholder:text-muted/60 focus:border-accent transition-colors"
        />
        <button
          type="button"
          aria-label={show ? "Hide key" : "Reveal key"}
          onClick={() => setShow(!show)}
          className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted hover:text-fg"
        >
          {show ? <EyeOff size={15} /> : <Eye size={15} />}
        </button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------- Slider
export function Slider({ value, onChange, min, max, step = 1, label, format }: {
  value: number; onChange: (v: number) => void; min: number; max: number;
  step?: number; label?: string; format?: (v: number) => string;
}) {
  return (
    <div className="py-1">
      {label && (
        <div className="flex justify-between text-xs mb-1.5">
          <span className="text-muted">{label}</span>
          <span className="font-medium">{format ? format(value) : value}</span>
        </div>
      )}
      <input
        type="range" min={min} max={max} step={step} value={value}
        aria-label={label}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-[rgb(var(--accent))] h-1.5"
      />
    </div>
  );
}

// -------------------------------------------------------------------- Badge
const BADGE_STYLES: Record<string, string> = {
  green: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  blue: "bg-sky-500/15 text-sky-400 border-sky-500/30",
  yellow: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  purple: "bg-violet-500/15 text-violet-400 border-violet-500/30",
  red: "bg-red-500/15 text-red-400 border-red-500/30",
  gray: "bg-elevated text-muted border-border",
};
export function Badge({ color = "gray", children, icon }: { color?: string; children: ReactNode; icon?: ReactNode }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
      BADGE_STYLES[color] ?? BADGE_STYLES.gray)}>
      {icon}{children}
    </span>
  );
}

// ------------------------------------------------------------------ Section
export function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <section className="mb-8 animate-slide-up">
      <h2 className="text-base font-semibold">{title}</h2>
      {description && <p className="text-xs text-muted mt-0.5 mb-3">{description}</p>}
      {!description && <div className="mb-3" />}
      <Card>{children}</Card>
    </section>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="flex items-start justify-between mb-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="text-sm text-muted mt-1">{subtitle}</p>}
      </div>
      {actions}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex items-center rounded-md border border-border bg-elevated px-1.5 py-0.5 text-[11px] font-mono text-muted">
      {children}
    </kbd>
  );
}
