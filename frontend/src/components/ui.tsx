import type { ReactNode } from "react";
import type { ApiErrorBody, FieldStatus, Severity } from "../types";

export function Card({ title, children, actions, className = "" }: {
  title?: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`min-w-0 rounded-xl border border-slate-200 bg-white shadow-sm ${className}`}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-3">
          <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
          {actions}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity=".25" strokeWidth="4" />
      <path d="M22 12a10 10 0 0 1-10 10" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
    </svg>
  );
}

const STATUS_STYLE: Record<FieldStatus, [string, string]> = {
  extracted: ["Extras", "bg-emerald-50 text-emerald-700 ring-emerald-200"],
  confirmed: ["Confirmat", "bg-emerald-50 text-emerald-700 ring-emerald-200"],
  needs_review: ["Necesită verificare", "bg-amber-50 text-amber-800 ring-amber-300"],
  missing: ["Lipsă", "bg-rose-50 text-rose-700 ring-rose-200"],
  not_on_document: ["Nu apare pe act", "bg-slate-100 text-slate-600 ring-slate-200"],
  corrected: ["Corectat", "bg-sky-50 text-sky-700 ring-sky-200"],
  excluded: ["Exclus", "bg-slate-100 text-slate-600 ring-slate-200"],
};

export function StatusBadge({ status }: { status: FieldStatus }) {
  const [label, cls] = STATUS_STYLE[status] ?? [status, "bg-slate-100 text-slate-600 ring-slate-200"];
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ${cls}`}>{label}</span>;
}

const SEV: Record<Severity, string> = {
  error: "text-rose-700",
  warning: "text-amber-700",
  info: "text-slate-500",
};
const SEV_DOT: Record<Severity, string> = {
  error: "bg-rose-500",
  warning: "bg-amber-500",
  info: "bg-slate-400",
};

export function SeverityDot({ severity }: { severity: Severity }) {
  return <span className={`mt-1.5 inline-block h-2 w-2 shrink-0 rounded-full ${SEV_DOT[severity]}`} />;
}

export function SeverityText({ severity, children }: { severity: Severity; children: ReactNode }) {
  return <span className={SEV[severity]}>{children}</span>;
}

export function ErrorBox({ error, onClose }: { error: ApiErrorBody; onClose?: () => void }) {
  const docLabel =
    error.document === "identity" ? "Act de identitate" : error.document === "registration" ? "Certificat de înmatriculare" : null;
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
      <svg className="mt-0.5 h-5 w-5 shrink-0" viewBox="0 0 20 20" fill="currentColor" aria-hidden>
        <path fillRule="evenodd" d="M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16ZM9 6a1 1 0 1 1 2 0v4a1 1 0 1 1-2 0V6Zm1 8.5a1.25 1.25 0 1 0 0-2.5 1.25 1.25 0 0 0 0 2.5Z" clipRule="evenodd" />
      </svg>
      <div className="flex-1">
        <p className="font-medium">
          {docLabel ? `${docLabel}: ` : ""}
          {error.message}
        </p>
        <p className="mt-1 font-mono text-xs text-rose-600">{error.code}</p>
        {error.issues && error.issues.length > 0 && (
          <ul className="mt-2 list-disc pl-5">
            {error.issues.map((i, k) => (
              <li key={k}>
                <span className="font-mono text-xs">{i.field}</span>: {i.message ?? i.code}
              </li>
            ))}
          </ul>
        )}
      </div>
      {onClose && (
        <button onClick={onClose} className="text-rose-500 hover:text-rose-700" aria-label="Închide">
          ×
        </button>
      )}
    </div>
  );
}

export function Button({
  children,
  variant = "primary",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" }) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2";
  const styles = {
    primary: "bg-indigo-600 text-white hover:bg-indigo-700 shadow-sm",
    secondary: "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50",
    ghost: "text-slate-600 hover:bg-slate-100",
  }[variant];
  return (
    <button className={`${base} ${styles} ${className}`} {...props}>
      {children}
    </button>
  );
}

export function DemoBanner({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <span className="rounded bg-amber-200 px-1.5 py-0.5 text-[11px] font-bold tracking-wide">DEMO</span>
      <div>{children}</div>
    </div>
  );
}
