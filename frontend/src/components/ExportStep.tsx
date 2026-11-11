import { useMemo, useState } from "react";
import type { Payload } from "../types";
import QuoteDemo from "./QuoteDemo";
import { Button, Card } from "./ui";

function JsonView({ json }: { json: string }) {
  // tiny syntax highlighter (keys / strings / numbers / null)
  const html = useMemo(
    () =>
      json
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(
          /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?)/g,
          (m, str, colon, lit, num) => {
            if (str) return colon ? `<span class="text-sky-300">${str}</span>${colon}` : `<span class="text-emerald-300">${str}</span>`;
            if (lit) return `<span class="text-fuchsia-300">${lit}</span>`;
            if (num) return `<span class="text-amber-300">${num}</span>`;
            return m;
          },
        ),
    [json],
  );
  return (
    <pre
      className="max-h-[36rem] overflow-auto rounded-lg bg-slate-900 p-4 font-mono text-xs leading-relaxed text-slate-200"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

export default function ExportStep({ payload, onRestart }: { payload: Payload; onRestart: () => void }) {
  const [copied, setCopied] = useState(false);
  const json = useMemo(() => JSON.stringify(payload, null, 2), [payload]);
  const corrected = Object.entries(payload.field_meta).filter(([, m]) => m.status === "corrected");
  const issues = payload.validation.issues.filter((i) => i.severity !== "info");

  const copy = async () => {
    await navigator.clipboard.writeText(json);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  const download = () => {
    const blob = new Blob([json], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `asigparse-${payload.processing_id}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <div className="min-w-0 space-y-6">
        <Card
          title="JSON final confirmat"
          actions={
            <div className="flex gap-2">
              <Button variant="secondary" onClick={copy}>
                {copied ? "Copiat ✓" : "Copiază"}
              </Button>
              <Button onClick={download}>Descarcă .json</Button>
            </div>
          }
        >
          <div className="mb-3 grid grid-cols-3 gap-3 text-center text-xs">
            <div className="rounded-lg bg-slate-50 p-2">
              <p className="text-lg font-semibold text-slate-800">{payload.schema_version}</p>
              <p className="text-slate-500">schema</p>
            </div>
            <div className="rounded-lg bg-sky-50 p-2">
              <p className="text-lg font-semibold text-sky-700">{corrected.length}</p>
              <p className="text-slate-500">câmpuri corectate</p>
            </div>
            <div className={`rounded-lg p-2 ${issues.length ? "bg-amber-50" : "bg-emerald-50"}`}>
              <p className={`text-lg font-semibold ${issues.length ? "text-amber-700" : "text-emerald-700"}`}>{issues.length}</p>
              <p className="text-slate-500">probleme rămase</p>
            </div>
          </div>
          <JsonView json={json} />
          <p className="mt-3 text-xs text-slate-500">{payload.disclaimer}</p>
        </Card>
        <div className="flex justify-start">
          <Button variant="secondary" onClick={onRestart}>
            Proces nou
          </Button>
        </div>
      </div>
      <QuoteDemo payload={payload} />
    </div>
  );
}
