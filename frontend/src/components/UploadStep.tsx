import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import type { ApiErrorBody, Health, Payload, SampleSet } from "../types";
import { Button, Card, ErrorBox, Spinner } from "./ui";

const ACCEPT = ".jpg,.jpeg,.png,.pdf,image/jpeg,image/png,application/pdf";
const OK_TYPES = ["image/jpeg", "image/png", "application/pdf"];

interface Props {
  health: Health | null;
  identity: File | null;
  registration: File | null;
  setIdentity: (f: File | null) => void;
  setRegistration: (f: File | null) => void;
  onExtracted: (p: Payload) => void;
}

function checkFile(f: File, maxMb: number): string | null {
  const ext = f.name.toLowerCase().split(".").pop() ?? "";
  if (!OK_TYPES.includes(f.type) && !["jpg", "jpeg", "png", "pdf"].includes(ext))
    return "Tip nesuportat. Folosiți JPG, PNG sau PDF.";
  if (f.size > maxMb * 1024 * 1024) return `Fișierul are ${(f.size / 1048576).toFixed(1)} MB (limita: ${maxMb} MB).`;
  if (f.size === 0) return "Fișierul este gol.";
  return null;
}

function DropZone({
  title,
  subtitle,
  file,
  onFile,
  maxMb,
}: {
  title: string;
  subtitle: string;
  file: File | null;
  onFile: (f: File | null) => void;
  maxMb: number;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!file || file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf")) {
      setUrl(null);
      return;
    }
    const u = URL.createObjectURL(file);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [file]);

  const accept = (f: File | undefined) => {
    if (!f) return;
    const err = checkFile(f, maxMb);
    setProblem(err);
    if (!err) onFile(f);
  };

  return (
    <div className="flex flex-col">
      <div className="mb-2 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
        <span className="text-xs text-slate-500">{subtitle}</span>
      </div>
      <div
        role="button"
        tabIndex={0}
        onClick={() => input.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          accept(e.dataTransfer.files[0]);
        }}
        className={`relative flex min-h-56 flex-1 cursor-pointer flex-col items-center justify-center overflow-hidden rounded-xl border-2 border-dashed p-4 text-center transition ${
          drag ? "border-indigo-500 bg-indigo-50" : file ? "border-emerald-300 bg-emerald-50/40" : "border-slate-300 bg-slate-50 hover:border-indigo-400 hover:bg-indigo-50/40"
        }`}
      >
        <input ref={input} type="file" accept={ACCEPT} className="hidden" onChange={(e) => accept(e.target.files?.[0])} />
        {file ? (
          <>
            {url ? (
              <img src={url} alt="previzualizare" className="max-h-44 rounded-md object-contain shadow" />
            ) : (
              <div className="flex h-32 w-24 items-center justify-center rounded-md bg-white text-lg font-bold text-rose-600 shadow ring-1 ring-slate-200">
                PDF
              </div>
            )}
            <p className="mt-3 max-w-full truncate text-sm font-medium text-slate-700">{file.name}</p>
            <p className="text-xs text-slate-500">{(file.size / 1024).toFixed(0)} KB · click pentru a înlocui</p>
          </>
        ) : (
          <>
            <svg className="h-10 w-10 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5" />
            </svg>
            <p className="mt-2 text-sm font-medium text-slate-700">Trageți fișierul aici sau click</p>
            <p className="text-xs text-slate-500">JPG, PNG sau PDF (max. 2 pagini) · până la {maxMb} MB</p>
          </>
        )}
      </div>
      <div className="mt-2 flex min-h-6 items-center justify-between">
        {problem ? <p className="text-xs text-rose-600">{problem}</p> : <span />}
        {file && (
          <button className="text-xs text-slate-500 hover:text-rose-600" onClick={() => onFile(null)}>
            Elimină
          </button>
        )}
      </div>
    </div>
  );
}

export default function UploadStep({ health, identity, registration, setIdentity, setRegistration, onExtracted }: Props) {
  const [samples, setSamples] = useState<SampleSet[]>([]);
  const [loadingSample, setLoadingSample] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<ApiErrorBody | null>(null);
  const maxMb = health?.max_upload_mb ?? 10;
  const [engine, setEngine] = useState<string | null>(null);
  const selectedEngine = engine ?? health?.ocr.engine ?? null;
  const ENGINE_LABEL: Record<string, string> = {
    oneocr: "OneOCR (Windows Snipping Tool) — recomandat",
    tesseract: "Tesseract (open-source, portabil)",
  };

  useEffect(() => {
    api.samples().then((r) => setSamples(r.sets)).catch(() => setSamples([]));
  }, []);

  useEffect(() => {
    if (!busy) return;
    const start = Date.now();
    const t = setInterval(() => setElapsed((Date.now() - start) / 1000), 200);
    return () => clearInterval(t);
  }, [busy]);

  const loadSample = async (s: SampleSet) => {
    setLoadingSample(s.id);
    setError(null);
    try {
      const [a, b] = await Promise.all([api.sampleFile(s.identity), api.sampleFile(s.registration)]);
      setIdentity(a);
      setRegistration(b);
    } catch (e) {
      setError(e instanceof ApiError ? e.body : { code: "SAMPLE_ERROR", message: String(e) });
    } finally {
      setLoadingSample(null);
    }
  };

  const run = async () => {
    setBusy(true);
    setError(null);
    setElapsed(0);
    try {
      onExtracted(await api.extract(identity, registration, selectedEngine ?? undefined));
    } catch (e) {
      setError(e instanceof ApiError ? e.body : { code: "UNKNOWN", message: String(e) });
    } finally {
      setBusy(false);
    }
  };

  const ocrDown =
    health !== null && !(selectedEngine ? health.engines?.[selectedEngine]?.available : health.ocr.available);

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="space-y-6 lg:col-span-2">
        <Card title="1. Încărcați documentele">
          <div className="grid gap-6 md:grid-cols-2">
            <DropZone title="Act de identitate" subtitle="CI model 1997 (CEI: suport limitat)" file={identity} onFile={setIdentity} maxMb={maxMb} />
            <DropZone title="Certificat de înmatriculare" subtitle="talon RO, fața cu datele" file={registration} onFile={setRegistration} maxMb={maxMb} />
          </div>
          <div className="mt-5 space-y-3">
            {error && <ErrorBox error={error} onClose={() => setError(null)} />}
            {ocrDown && (
              <ErrorBox
                error={{
                  code: "OCR_UNAVAILABLE",
                  message: "Motorul OCR selectat nu este disponibil pe server. Vezi README (OneOCR: scripts/setup_oneocr.ps1; Tesseract: instalare + ron).",
                }}
              />
            )}
            {health?.engines && (
              <div className="flex flex-wrap items-center gap-3 rounded-lg bg-slate-50 px-3 py-2 text-xs">
                <label htmlFor="engine" className="font-medium text-slate-700">
                  Motor OCR
                </label>
                <select
                  id="engine"
                  className="rounded-md border border-slate-300 bg-white px-2 py-1"
                  value={selectedEngine ?? ""}
                  onChange={(e) => setEngine(e.target.value)}
                >
                  {Object.entries(health.engines).map(([name, info]) => (
                    <option key={name} value={name} disabled={!info.available}>
                      {(ENGINE_LABEL[name] ?? name) + (info.available ? "" : " — indisponibil")}
                    </option>
                  ))}
                </select>
                {selectedEngine && !health.engines[selectedEngine]?.available && (
                  <span className="text-rose-600">{health.engines[selectedEngine]?.reason}</span>
                )}
                <span className="text-slate-400">Ambele rulează local; comparație în docs/OCR_BENCHMARK.md.</span>
              </div>
            )}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs text-slate-500">
                Puteți încărca și un singur document; câmpurile lipsă vor fi semnalate și pot fi completate manual.
              </p>
              <Button onClick={run} disabled={busy || ocrDown || (!identity && !registration)}>
                {busy ? (
                  <>
                    <Spinner /> OCR în curs… {elapsed.toFixed(1)}s
                  </>
                ) : (
                  "Procesează documentele"
                )}
              </Button>
            </div>
            {busy && (
              <p className="text-xs text-slate-500">
                OCR local ({selectedEngine === "oneocr" ? "OneOCR, ~0,2 s/document" : "Tesseract ron+eng, ~2 s/document"}) → mapare câmpuri → validări.
              </p>
            )}
          </div>
        </Card>
      </div>

      <div className="space-y-6">
        <Card title="Seturi demo sintetice">
          <p className="mb-3 text-xs text-slate-500">
            Imagini generate local cu <strong>date integral fictive</strong> (marcate SPECIMEN). Ele trec prin același OCR real
            ca orice fișier încărcat — rezultatele nu sunt precompletate.
          </p>
          {samples.length === 0 && <p className="text-xs text-slate-400">Nu s-au găsit mostre (rulați scripts/generate_samples.py).</p>}
          <ul className="space-y-2">
            {samples.map((s) => (
              <li key={s.id}>
                <button
                  onClick={() => loadSample(s)}
                  disabled={loadingSample !== null || busy}
                  className="w-full rounded-lg border border-slate-200 p-3 text-left transition hover:border-indigo-300 hover:bg-indigo-50/50 disabled:opacity-50"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium text-slate-800">{s.title}</span>
                    {loadingSample === s.id && <Spinner />}
                  </div>
                  <p className="mt-1 text-xs text-slate-500">{s.description}</p>
                </button>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Confidențialitate">
          <ul className="list-disc space-y-1 pl-4 text-xs text-slate-600">
            <li>Procesare locală; imaginile nu sunt salvate pe disc și nu sunt trimise către servicii externe.</li>
            <li>Rezultatul extragerii este păstrat doar în memorie (max. 30 min) pentru confirmare.</li>
            <li>CNP-ul și conținutul documentelor nu sunt scrise în loguri.</li>
            <li>Nu încărcați documente reale ale unor terți în demo.</li>
          </ul>
        </Card>
      </div>
    </div>
  );
}
