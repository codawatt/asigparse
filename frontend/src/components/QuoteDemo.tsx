import { useMemo, useState } from "react";
import type { Payload } from "../types";
import { Button, Card, DemoBanner } from "./ui";

/**
 * Demonstration of how the confirmed JSON pre-fills an RCA quotation form.
 * No tariff is computed and nothing is sent anywhere: the "request" shown is a
 * sample mapping (internal schema -> hypothetical insurer adapter).
 */

type Q = Record<string, string>;

const today = () => new Date().toISOString().slice(0, 10);

function initial(p: Payload): Q {
  const v = p.vehicle;
  const person = [p.person.last_name, p.person.first_name].filter(Boolean).join(" ");
  return {
    insured_name: person,
    insured_cnp: p.person.national_id ?? "",
    insured_address: p.person.address ?? "",
    plate: v.registration_number ?? "",
    vin: v.vin ?? "",
    make_model: [v.make, v.model].filter(Boolean).join(" "),
    engine_cc: v.engine_cc?.toString() ?? "",
    power_kw: v.power_kw?.toString() ?? "",
    fuel: v.fuel ?? "",
    first_registration: v.first_registration ?? "",
    holder: v.certificate_holder?.name ?? "",
    owner: v.legal_owner?.name ?? "",
    start_date: today(),
    period_months: "12",
    usage: "personal",
  };
}

const LABELS: [keyof Q, string, "prefill" | "manual"][] = [
  ["insured_name", "Asigurat / contractant", "prefill"],
  ["insured_cnp", "CNP", "prefill"],
  ["insured_address", "Adresă asigurat", "prefill"],
  ["plate", "Nr. înmatriculare", "prefill"],
  ["vin", "Serie șasiu (VIN)", "prefill"],
  ["make_model", "Marcă / model", "prefill"],
  ["engine_cc", "Cilindree (cm³)", "prefill"],
  ["power_kw", "Putere (kW)", "prefill"],
  ["fuel", "Combustibil", "prefill"],
  ["first_registration", "Prima înmatriculare", "prefill"],
  ["holder", "Titular certificat (C.1)", "prefill"],
  ["owner", "Proprietar (C.2)", "prefill"],
];

export default function QuoteDemo({ payload }: { payload: Payload }) {
  const [q, setQ] = useState<Q>(() => initial(payload));
  const [request, setRequest] = useState<object | null>(null);
  const missing = LABELS.filter(([k, , src]) => src === "prefill" && !q[k] && k !== "owner" && k !== "insured_cnp").map(([, l]) => l);
  const set = (k: string, v: string) => setQ((s) => ({ ...s, [k]: v }));

  const holderDiffers = useMemo(
    () => q.holder && q.insured_name && q.holder.replace(/[\s-]+/g, " ").split(" ").sort().join(" ") !== q.insured_name.replace(/[\s-]+/g, " ").split(" ").sort().join(" "),
    [q.holder, q.insured_name],
  );

  const build = () =>
    setRequest({
      _note: "Exemplu de mapare către un adaptor ipotetic de asigurător. NU a fost trimis nicăieri.",
      product: "RCA",
      source_processing_id: payload.processing_id,
      policy: { start_date: q.start_date, period_months: Number(q.period_months), usage: q.usage },
      policyholder: { full_name: q.insured_name || null, personal_code: q.insured_cnp || null, address: q.insured_address || null },
      vehicle: {
        plate: q.plate || null,
        vin: q.vin || null,
        make_model: q.make_model || null,
        engine_capacity_cm3: q.engine_cc ? Number(q.engine_cc) : null,
        power_kw: q.power_kw ? Number(q.power_kw) : null,
        fuel_type: q.fuel || null,
        first_registration_date: q.first_registration || null,
        registration_holder: q.holder || null,
        owner: q.owner || null,
      },
      premium: null,
    });

  return (
    <Card title="Formular demonstrativ de ofertare RCA">
      <DemoBanner>
        Integrare <strong>demonstrativă</strong>: nu se calculează prime, nu se emit polițe și nu se contactează niciun
        asigurător. Câmpurile sunt precompletate din JSON-ul confirmat; restul se completează manual.
      </DemoBanner>
      <form
        className="mt-4 grid gap-x-4 gap-y-3 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          build();
        }}
      >
        {LABELS.map(([k, label]) => (
          <label key={k} className={`text-xs ${k === "insured_address" || k === "vin" ? "sm:col-span-2" : ""}`}>
            <span className="mb-1 flex items-center gap-1.5 font-medium text-slate-700">
              {label}
              {q[k] ? (
                <span className="rounded bg-indigo-50 px-1 text-[10px] text-indigo-600">din JSON</span>
              ) : (
                <span className="rounded bg-slate-100 px-1 text-[10px] text-slate-500">gol</span>
              )}
            </span>
            <input
              className={`w-full rounded-md border border-slate-300 px-3 py-2 text-sm ${k === "insured_cnp" ? "[-webkit-text-security:disc]" : ""}`}
              value={q[k]}
              onChange={(e) => set(k, e.target.value)}
            />
          </label>
        ))}
        <div className="sm:col-span-2 mt-2 border-t border-slate-100 pt-3 text-xs font-semibold text-slate-700">Date completate de operator</div>
        <label className="text-xs">
          <span className="mb-1 block font-medium text-slate-700">Data început</span>
          <input type="date" className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" value={q.start_date} onChange={(e) => set("start_date", e.target.value)} />
        </label>
        <label className="text-xs">
          <span className="mb-1 block font-medium text-slate-700">Perioadă</span>
          <select className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" value={q.period_months} onChange={(e) => set("period_months", e.target.value)}>
            <option value="1">1 lună</option>
            <option value="6">6 luni</option>
            <option value="12">12 luni</option>
          </select>
        </label>
        <label className="text-xs sm:col-span-2">
          <span className="mb-1 block font-medium text-slate-700">Utilizare</span>
          <select className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" value={q.usage} onChange={(e) => set("usage", e.target.value)}>
            <option value="personal">Personală</option>
            <option value="business">În interes de serviciu</option>
            <option value="ride_sharing">Ride-sharing / taxi</option>
          </select>
        </label>

        <div className="space-y-2 sm:col-span-2">
          {holderDiffers && (
            <p className="rounded-md bg-sky-50 p-2 text-xs text-sky-800">
              Titularul certificatului diferă de persoana din actul de identitate. Stabiliți cine este contractantul
              înainte de ofertare.
            </p>
          )}
          {missing.length > 0 && (
            <p className="rounded-md bg-amber-50 p-2 text-xs text-amber-800">Necompletate: {missing.join(", ")}.</p>
          )}
          <Button type="submit">Generează cererea demonstrativă</Button>
        </div>
      </form>

      {request && (
        <div className="mt-4 space-y-2">
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
            <p className="font-medium text-slate-800">Primă: — </p>
            <p className="text-xs text-slate-500">
              Nu este calculată. Într-o integrare reală, cererea de mai jos ar fi trimisă prin adaptorul asigurătorului ales.
            </p>
          </div>
          <pre className="max-h-80 overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-[11px] text-slate-200">
            {JSON.stringify({ ...request, policyholder: { ...(request as { policyholder: object }).policyholder, personal_code: q.insured_cnp ? "•••••••••••••" : null } }, null, 2)}
          </pre>
        </div>
      )}
    </Card>
  );
}
