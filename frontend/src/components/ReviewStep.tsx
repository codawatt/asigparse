import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api";
import { ALL_FIELDS, FIELD_BY_PATH, fromForm, GROUPS, toForm, type FormValues } from "../fields";
import type { ApiErrorBody, Issue, Payload } from "../types";
import FieldInput from "./FieldInput";
import { Button, Card, ErrorBox, SeverityDot, SeverityText, Spinner } from "./ui";

interface Props {
  extraction: Payload;
  files: { identity: File | null; registration: File | null };
  threshold: number;
  onConfirmed: (p: Payload) => void;
  onRestart: () => void;
}

function Preview({ file, label }: { file: File | null; label: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [zoom, setZoom] = useState(false);
  const isPdf = !!file && (file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf"));
  useEffect(() => {
    if (!file) return;
    const u = URL.createObjectURL(file);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [file]);
  if (!file) return <div className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-xs text-slate-400">{label}: neîncărcat</div>;
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-slate-600">{label}</p>
      {isPdf ? (
        <object data={url ?? undefined} type="application/pdf" className="h-72 w-full rounded-lg border border-slate-200">
          <a href={url ?? undefined} target="_blank" rel="noreferrer" className="text-xs text-indigo-600 underline">
            Deschide PDF
          </a>
        </object>
      ) : (
        <>
          <img
            src={url ?? undefined}
            alt={label}
            onClick={() => setZoom(true)}
            className="max-h-72 w-full cursor-zoom-in rounded-lg border border-slate-200 bg-slate-50 object-contain"
          />
          {zoom && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/80 p-6" onClick={() => setZoom(false)}>
              <img src={url ?? undefined} alt={label} className="max-h-full max-w-full rounded-lg bg-white shadow-2xl" />
            </div>
          )}
        </>
      )}
    </div>
  );
}

function bodyFor(processingId: string, values: FormValues, ownerPresent: boolean, docType: string | null, extra = {}) {
  const { person, vehicle } = fromForm(values, ownerPresent, docType);
  return { processing_id: processingId, corrected_person: person, corrected_vehicle: vehicle, ...extra };
}

export default function ReviewStep({ extraction, files, threshold, onConfirmed, onRestart }: Props) {
  const original = useMemo(() => toForm(extraction), [extraction]);
  const [values, setValues] = useState<FormValues>(original);
  const [current, setCurrent] = useState<Payload>(extraction); // latest server validation
  const [validatedValues, setValidatedValues] = useState<FormValues>(original);
  const [ownerPresent, setOwnerPresent] = useState(extraction.vehicle.legal_owner !== null);
  const [validatedOwner, setValidatedOwner] = useState(ownerPresent);
  const [reviewed, setReviewed] = useState(false);
  const [ack, setAck] = useState(false);
  const [excludeCnp, setExcludeCnp] = useState(false);
  const [busy, setBusy] = useState<"validate" | "confirm" | null>(null);
  const [error, setError] = useState<ApiErrorBody | null>(null);
  const [showOcr, setShowOcr] = useState(false);
  const docType = extraction.person.identity_document.type;

  const dirty = ALL_FIELDS.some((f) => values[f.path] !== validatedValues[f.path]) || ownerPresent !== validatedOwner;
  const correctedCount = ALL_FIELDS.filter((f) => values[f.path] !== original[f.path]).length;

  const issuesByField = useMemo(() => {
    const m: Record<string, Issue[]> = {};
    for (const i of current.validation.issues) (m[i.field] ??= []).push(i);
    return m;
  }, [current]);
  const generalIssues = current.validation.issues.filter((i) => !FIELD_BY_PATH[i.field]);
  const counts = current.validation.issues.reduce(
    (acc, i) => ({ ...acc, [i.severity]: acc[i.severity] + 1 }),
    { error: 0, warning: 0, info: 0 } as Record<string, number>,
  );
  const reviewCount = ALL_FIELDS.filter((f) => current.field_meta[f.path]?.review_required).length;

  const setValue = (path: string, v: string) => setValues((s) => ({ ...s, [path]: v }));

  const revalidate = async () => {
    setBusy("validate");
    setError(null);
    try {
      const res = await api.validate(bodyFor(extraction.processing_id, values, ownerPresent, docType, { exclude_national_id: excludeCnp }));
      setCurrent(res);
      setValidatedValues(values);
      setValidatedOwner(ownerPresent);
    } catch (e) {
      setError(e instanceof ApiError ? e.body : { code: "UNKNOWN", message: String(e) });
    } finally {
      setBusy(null);
    }
  };

  const confirm = async () => {
    setBusy("confirm");
    setError(null);
    try {
      const res = await api.confirm(
        bodyFor(extraction.processing_id, values, ownerPresent, docType, {
          acknowledge_issues: ack,
          exclude_national_id: excludeCnp,
        }),
      );
      onConfirmed(res.payload);
    } catch (e) {
      const body = e instanceof ApiError ? e.body : { code: "UNKNOWN", message: String(e) };
      setError(body);
      if (body.code === "UNRESOLVED_ERRORS") await revalidate().catch(() => {});
    } finally {
      setBusy(null);
    }
  };

  const unresolvedErrors = !dirty && counts.error > 0;

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
      {/* left: documents + diagnostics */}
      <div className="min-w-0 space-y-6">
        <Card title="Documente sursă">
          <div className="space-y-4">
            <Preview file={files.identity} label="Act de identitate" />
            <Preview file={files.registration} label="Certificat de înmatriculare" />
          </div>
        </Card>
        <Card
          title="Diagnostic OCR"
          actions={
            <button className="text-xs text-indigo-600 hover:underline" onClick={() => setShowOcr((s) => !s)}>
              {showOcr ? "ascunde textul brut" : "arată textul brut"}
            </button>
          }
        >
          <ul className="space-y-3 text-xs">
            {extraction.documents.map((d) => (
              <li key={d.slot} className="rounded-lg bg-slate-50 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium text-slate-700">
                    {d.slot === "identity" ? "Act de identitate" : "Certificat înmatriculare"} · {d.detected_type}
                  </span>
                  <span className="tabular-nums text-slate-500">
                    {d.ocr_engine} · încredere medie {d.ocr_mean_confidence !== null ? Math.round(d.ocr_mean_confidence * 100) + "%" : "–"}
                  </span>
                </div>
                <p className="mt-1 text-slate-500">
                  {d.file_type} · {d.pages_processed} pag. · {d.quality[0]?.width}×{d.quality[0]?.height}px
                  {d.rotation_applied.some((r) => r) && ` · rotit ${d.rotation_applied.join("/")}°`}
                </p>
                {d.codes_found && <p className="mt-1 text-slate-500">Coduri găsite: {d.codes_found.join(", ") || "—"}</p>}
                {showOcr && d.ocr_text && (
                  <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap rounded bg-slate-900 p-2 font-mono text-[11px] text-slate-100">
                    {d.ocr_text}
                  </pre>
                )}
              </li>
            ))}
          </ul>
          <p className="mt-3 text-[11px] text-slate-400">
            Timp procesare: {extraction.processing_time_ms} ms. Textul brut este afișat doar aici, nu este stocat pe server.
          </p>
        </Card>
      </div>

      {/* right: review form */}
      <div className="min-w-0 space-y-6">
        <div
          className={`rounded-xl border p-4 ${counts.error ? "border-rose-200 bg-rose-50" : counts.warning || reviewCount ? "border-amber-200 bg-amber-50" : "border-emerald-200 bg-emerald-50"}`}
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-slate-800">
                {counts.error
                  ? "Există erori de validare — corectați înainte de export"
                  : reviewCount
                    ? `${reviewCount} câmpuri necesită verificare`
                    : "Toate câmpurile au trecut verificările automate"}
              </p>
              <p className="mt-0.5 text-xs text-slate-600">
                {counts.error} erori · {counts.warning} avertismente · {counts.info} informări · prag încredere {Math.round(threshold * 100)}%
                {correctedCount > 0 && ` · ${correctedCount} câmpuri corectate`}
              </p>
            </div>
            <span className="rounded-full bg-white/70 px-2 py-1 font-mono text-[11px] text-slate-500">id {extraction.processing_id}</span>
          </div>
          {generalIssues.length > 0 && (
            <ul className="mt-3 space-y-1 border-t border-black/5 pt-3 text-xs">
              {generalIssues.map((i, k) => (
                <li key={k} className="flex gap-2">
                  <SeverityDot severity={i.severity} />
                  <SeverityText severity={i.severity}>{i.message ?? i.code}</SeverityText>
                </li>
              ))}
            </ul>
          )}
        </div>

        {GROUPS.map((g) => {
          const isOwner = g.id === "owner";
          return (
            <Card
              key={g.id}
              title={g.title}
              actions={
                isOwner ? (
                  <label className="flex items-center gap-2 text-xs text-slate-600">
                    <input type="checkbox" checked={ownerPresent} onChange={(e) => setOwnerPresent(e.target.checked)} />
                    C.2 apare pe certificat
                  </label>
                ) : undefined
              }
            >
              {g.note && <p className="-mt-1 mb-4 text-xs text-slate-500">{g.note}</p>}
              {isOwner && !ownerPresent && (issuesByField["vehicle.legal_owner.name"] ?? []).map((i, k) => (
                <p key={k} className="mb-3 flex gap-2 text-xs">
                  <SeverityDot severity={i.severity} />
                  <SeverityText severity={i.severity}>{i.message}</SeverityText>
                </p>
              ))}
              {(!isOwner || ownerPresent) && (
                <div className="grid gap-x-5 gap-y-4 sm:grid-cols-2">
                  {g.fields.map((f) => (
                    <FieldInput
                      key={f.path}
                      def={f}
                      value={values[f.path]}
                      original={original[f.path]}
                      stale={values[f.path] !== validatedValues[f.path]}
                      meta={current.field_meta[f.path]}
                      issues={issuesByField[f.path] ?? []}
                      threshold={threshold}
                      disabled={f.path === "person.national_id" && excludeCnp}
                      onChange={(v) => setValue(f.path, v)}
                    />
                  ))}
                </div>
              )}
            </Card>
          );
        })}

        <Card title="Confirmare operator">
          <div className="space-y-3 text-sm">
            <label className="flex items-start gap-2">
              <input type="checkbox" className="mt-1" checked={excludeCnp} onChange={(e) => setExcludeCnp(e.target.checked)} />
              <span>
                Exclude CNP-ul din exportul final <span className="text-xs text-slate-500">(minimizarea datelor, dacă fluxul de ofertare nu îl cere)</span>
              </span>
            </label>
            <label className="flex items-start gap-2">
              <input type="checkbox" className="mt-1" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />
              <span>Am verificat valorile față de documentele originale și am corectat unde a fost necesar.</span>
            </label>
            {unresolvedErrors && (
              <label className="flex items-start gap-2 text-rose-700">
                <input type="checkbox" className="mt-1" checked={ack} onChange={(e) => setAck(e.target.checked)} />
                <span>Export conștient cu {counts.error} erori nerezolvate (vor rămâne marcate în JSON).</span>
              </label>
            )}
            {error && <ErrorBox error={error} onClose={() => setError(null)} />}
            <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
              <Button variant="ghost" onClick={onRestart}>
                ← Documente noi
              </Button>
              <div className="flex flex-wrap gap-3">
                <Button variant="secondary" onClick={revalidate} disabled={busy !== null}>
                  {busy === "validate" && <Spinner />} Revalidează{dirty ? " modificările" : ""}
                </Button>
                <Button onClick={confirm} disabled={busy !== null || !reviewed || (unresolvedErrors && !ack)}>
                  {busy === "confirm" && <Spinner />} Confirmă și exportă JSON
                </Button>
              </div>
            </div>
            {!reviewed && <p className="text-right text-xs text-slate-400">Bifați verificarea pentru a putea confirma.</p>}
          </div>
        </Card>
      </div>
    </div>
  );
}
