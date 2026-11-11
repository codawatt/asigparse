import { useState } from "react";
import { cnpHint, FUEL_OPTIONS, vinHint, type FieldDef } from "../fields";
import type { FieldMeta, FieldStatus, Issue } from "../types";
import { SeverityDot, SeverityText, StatusBadge } from "./ui";

interface Props {
  def: FieldDef;
  value: string;
  original: string;
  /** value edited since the last server validation */
  stale: boolean;
  meta: FieldMeta | undefined;
  issues: Issue[];
  threshold: number;
  disabled?: boolean;
  onChange: (v: string) => void;
}

function sourceLabel(source: string | null): string | null {
  if (!source) return null;
  if (source === "operator") return "operator";
  return source.replace(/^identity\./, "CI · ").replace(/^registration\./, "talon · ");
}

export default function FieldInput({ def, value, original, stale, meta, issues, threshold, disabled, onChange }: Props) {
  const [showCnp, setShowCnp] = useState(false);
  const changed = value !== original;
  const status: FieldStatus = changed ? "corrected" : meta?.status ?? "missing";
  const conf = changed ? null : meta?.confidence ?? null;
  const low = conf !== null && conf < threshold;
  const hasError = !stale && issues.some((i) => i.severity === "error");
  const needsReview = !stale && !changed && (meta?.review_required ?? false);

  // instant client-side hint only while the server has not validated the edit yet
  const liveHint = !stale ? null : def.kind === "cnp" ? cnpHint(value) : def.kind === "vin" ? vinHint(value) : null;

  const ring = hasError
    ? "border-rose-300 bg-rose-50/50 focus:ring-rose-400"
    : changed
      ? "border-sky-300 bg-sky-50/40 focus:ring-sky-400"
      : needsReview || low
        ? "border-amber-300 bg-amber-50/60 focus:ring-amber-400"
        : "border-slate-300 bg-white focus:ring-indigo-400";

  const inputCls = `w-full rounded-md border px-3 py-2 text-sm shadow-sm outline-none transition focus:ring-2 disabled:bg-slate-100 disabled:text-slate-400 ${ring}`;
  const id = `f-${def.path}`;

  return (
    <div className={def.wide ? "sm:col-span-2" : ""}>
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <label htmlFor={id} className="text-xs font-medium text-slate-700">
          {def.label}
          {def.critical && <span className="ml-0.5 text-rose-500">*</span>}
        </label>
        {def.code && <span className="rounded bg-slate-100 px-1.5 font-mono text-[10px] text-slate-500">{def.code}</span>}
        <StatusBadge status={status} />
        {conf !== null && (
          <span
            className={`text-[11px] tabular-nums ${low ? "font-semibold text-amber-700" : "text-slate-400"}`}
            title="Încredere OCR (indică incertitudinea tehnică, nu autenticitatea)"
          >
            {Math.round(conf * 100)}%
          </span>
        )}
        {!changed && meta?.checks?.includes("cnp_checksum") && <span className="text-[11px] text-emerald-600">✓ checksum</span>}
        {!changed && meta?.checks?.includes("mrz_check_digit") && <span className="text-[11px] text-emerald-600">✓ MRZ</span>}
      </div>

      <div className="relative">
        {def.kind === "fuel" ? (
          <select id={id} className={inputCls} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
            <option value="">— necompletat —</option>
            {FUEL_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        ) : (
          <input
            id={id}
            className={`${inputCls} ${def.kind === "vin" || def.kind === "cnp" ? "font-mono tracking-wide" : ""} ${
              def.kind === "cnp" && !showCnp ? "[-webkit-text-security:disc]" : ""
            } ${def.kind === "cnp" ? "pr-16" : ""}`}
            value={value}
            disabled={disabled}
            inputMode={def.kind === "number" || def.kind === "cnp" ? "numeric" : undefined}
            placeholder={def.kind === "date" ? "AAAA-LL-ZZ" : def.placeholder ?? (status === "missing" || status === "not_on_document" ? "necompletat (null)" : "")}
            autoComplete="off"
            spellCheck={false}
            onChange={(e) => onChange(def.kind === "vin" ? e.target.value.toUpperCase() : e.target.value)}
          />
        )}
        {def.kind === "cnp" && (
          <button
            type="button"
            onClick={() => setShowCnp((s) => !s)}
            className="absolute inset-y-0 right-2 my-auto h-6 rounded px-1.5 text-[11px] text-slate-500 hover:bg-slate-100"
          >
            {showCnp ? "ascunde" : "arată"}
          </button>
        )}
      </div>

      <div className="mt-1 space-y-0.5 text-[11px] leading-snug">
        {changed && original !== "" && (
          <p className="text-sky-700">
            OCR: <span className="font-mono">{def.kind === "cnp" && !showCnp ? "•••••••••••••" : original}</span>{" "}
            <button type="button" className="underline hover:text-sky-900" onClick={() => onChange(original)}>
              revino
            </button>
          </p>
        )}
        {liveHint && <p className="text-rose-600">{liveHint}</p>}
        {stale && <p className="text-slate-400">modificat — validat la „Revalidează” / confirmare</p>}
        {!stale &&
          issues.map((i, k) => (
            <p key={k} className="flex gap-1.5">
              <SeverityDot severity={i.severity} />
              <SeverityText severity={i.severity}>
                {i.message ?? i.code}
                {i.suggestion && (
                  <>
                    {" "}
                    <button type="button" className="font-medium underline" onClick={() => onChange(i.suggestion!)}>
                      Aplică sugestia: <span className="font-mono">{i.suggestion}</span>
                    </button>
                  </>
                )}
              </SeverityText>
            </p>
          ))}
        {!changed && meta?.reason && !issues.some((i) => i.message === meta.reason) && (
          <p className="text-slate-500">{meta.reason}</p>
        )}
        {!changed && sourceLabel(meta?.source ?? null) && (
          <p className="text-slate-400">sursă: {sourceLabel(meta?.source ?? null)}</p>
        )}
      </div>
    </div>
  );
}
