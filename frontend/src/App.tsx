import { useEffect, useState } from "react";
import { api } from "./api";
import ExportStep from "./components/ExportStep";
import ReviewStep from "./components/ReviewStep";
import UploadStep from "./components/UploadStep";
import type { Health, Payload } from "./types";

type Step = "upload" | "review" | "export";

const STEPS: { id: Step; label: string }[] = [
  { id: "upload", label: "Încărcare" },
  { id: "review", label: "Revizuire" },
  { id: "export", label: "Export & ofertă" },
];

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [step, setStep] = useState<Step>("upload");
  const [identity, setIdentity] = useState<File | null>(null);
  const [registration, setRegistration] = useState<File | null>(null);
  const [extraction, setExtraction] = useState<Payload | null>(null);
  const [confirmed, setConfirmed] = useState<Payload | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealthError(true));
  }, []);

  const restart = () => {
    if (extraction) api.discard(extraction.processing_id);
    setExtraction(null);
    setConfirmed(null);
    setIdentity(null);
    setRegistration(null);
    setStep("upload");
  };

  const stepIndex = STEPS.findIndex((s) => s.id === step);

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white">AP</div>
            <div>
              <h1 className="text-base font-semibold text-slate-900">AsigParse OCR</h1>
              <p className="text-xs text-slate-500">CI + certificat de înmatriculare → date verificate pentru ofertare · MVP demonstrativ</p>
            </div>
          </div>
          <nav className="flex items-center gap-2 text-sm">
            {STEPS.map((s, i) => (
              <div key={s.id} className="flex items-center gap-2">
                <span
                  className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold ${
                    i < stepIndex ? "bg-emerald-500 text-white" : i === stepIndex ? "bg-indigo-600 text-white" : "bg-slate-200 text-slate-500"
                  }`}
                >
                  {i < stepIndex ? "✓" : i + 1}
                </span>
                <span className={i === stepIndex ? "font-medium text-slate-900" : "text-slate-500"}>{s.label}</span>
                {i < STEPS.length - 1 && <span className="mx-1 h-px w-6 bg-slate-300" />}
              </div>
            ))}
          </nav>
          <div className="text-xs">
            {healthError ? (
              <span className="rounded-full bg-rose-100 px-2 py-1 text-rose-700">API indisponibil</span>
            ) : health ? (
              <span
                className={`rounded-full px-2 py-1 ${health.ocr.available ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-700"}`}
                title={health.ocr.missing_languages.length ? `Limbi lipsă: ${health.ocr.missing_languages.join(", ")}` : undefined}
              >
                {health.ocr.available ? `Tesseract ${health.ocr.version ?? ""} · ${health.ocr.languages}` : "OCR indisponibil"}
              </span>
            ) : (
              <span className="text-slate-400">verificare API…</span>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-8">
        {healthError && (
          <div className="mb-6 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
            Backend-ul nu răspunde la <code>/api/v1/health</code>. Porniți API-ul:{" "}
            <code className="rounded bg-white px-1">uvicorn app.main:app --port 8000</code> (vezi README).
          </div>
        )}
        {step === "upload" && (
          <UploadStep
            health={health}
            identity={identity}
            registration={registration}
            setIdentity={setIdentity}
            setRegistration={setRegistration}
            onExtracted={(p) => {
              setExtraction(p);
              setStep("review");
            }}
          />
        )}
        {step === "review" && extraction && (
          <ReviewStep
            key={extraction.processing_id}
            extraction={extraction}
            files={{ identity, registration }}
            threshold={health?.confidence_threshold ?? 0.85}
            onConfirmed={(p) => {
              setConfirmed(p);
              setStep("export");
            }}
            onRestart={restart}
          />
        )}
        {step === "export" && confirmed && <ExportStep payload={confirmed} onRestart={restart} />}
      </main>

      <footer className="mx-auto max-w-7xl px-6 pb-8 text-[11px] text-slate-400">
        OCR-ul nu dovedește identitatea persoanei și nu verifică oficial datele. Scorul de încredere indică incertitudinea
        tehnică, nu autenticitatea documentului. Demo fără autentificare — nu folosiți în producție.
      </footer>
    </div>
  );
}
