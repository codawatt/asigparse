import type { Party, Payload, Person, Vehicle } from "./types";

export type FieldKind = "text" | "number" | "date" | "fuel" | "cnp" | "vin";

export interface FieldDef {
  path: string;
  label: string;
  code?: string; // document code / label shown as a hint
  kind: FieldKind;
  critical?: boolean;
  wide?: boolean;
  placeholder?: string;
}

export interface FieldGroup {
  id: string;
  title: string;
  note?: string;
  fields: FieldDef[];
}

export const FUEL_OPTIONS: { value: string; label: string }[] = [
  { value: "PETROL", label: "Benzină (PETROL)" },
  { value: "DIESEL", label: "Motorină (DIESEL)" },
  { value: "LPG", label: "GPL (LPG)" },
  { value: "CNG", label: "GNC (CNG)" },
  { value: "ELECTRIC", label: "Electric" },
  { value: "HYBRID_PETROL", label: "Hibrid benzină" },
  { value: "HYBRID_DIESEL", label: "Hibrid motorină" },
  { value: "HYDROGEN", label: "Hidrogen" },
  { value: "OTHER", label: "Altul (nemapat)" },
];

export const GROUPS: FieldGroup[] = [
  {
    id: "person",
    title: "Persoană",
    fields: [
      { path: "person.last_name", label: "Nume", kind: "text", critical: true },
      { path: "person.first_name", label: "Prenume", kind: "text", critical: true },
      { path: "person.national_id", label: "CNP", kind: "cnp" },
      { path: "person.address", label: "Domiciliu", kind: "text", wide: true },
    ],
  },
  {
    id: "id_doc",
    title: "Act de identitate",
    fields: [
      { path: "person.identity_document.series", label: "Serie", kind: "text" },
      { path: "person.identity_document.number", label: "Număr", kind: "text" },
      { path: "person.identity_document.expiry_date", label: "Valabil până la", kind: "date" },
    ],
  },
  {
    id: "vehicle",
    title: "Vehicul",
    fields: [
      { path: "vehicle.registration_number", label: "Nr. înmatriculare", code: "A", kind: "text", critical: true },
      { path: "vehicle.vin", label: "VIN", code: "E", kind: "vin", critical: true, wide: true },
      { path: "vehicle.make", label: "Marcă", code: "D.1", kind: "text", critical: true },
      { path: "vehicle.model", label: "Model / denumire comercială", code: "D.3", kind: "text", critical: true },
      { path: "vehicle.first_registration", label: "Prima înmatriculare", code: "B", kind: "date" },
      { path: "vehicle.vehicle_type", label: "Tip / variantă", code: "D.2", kind: "text" },
    ],
  },
  {
    id: "tech",
    title: "Date tehnice",
    fields: [
      { path: "vehicle.engine_cc", label: "Cilindree (cm³)", code: "P.1", kind: "number", critical: true },
      { path: "vehicle.power_kw", label: "Putere (kW)", code: "P.2", kind: "number" },
      { path: "vehicle.fuel", label: "Combustibil", code: "P.3", kind: "fuel" },
      { path: "vehicle.category", label: "Categorie", code: "J", kind: "text" },
      { path: "vehicle.max_permissible_mass_kg", label: "Masă maximă (kg)", code: "F.1", kind: "number" },
      { path: "vehicle.seats", label: "Locuri", code: "S.1", kind: "number" },
      { path: "vehicle.color", label: "Culoare", code: "R", kind: "text" },
    ],
  },
  {
    id: "holder",
    title: "Titular certificat (C.1)",
    fields: [
      { path: "vehicle.certificate_holder.name", label: "Nume / denumire", code: "C.1.1+C.1.2", kind: "text", wide: true },
      { path: "vehicle.certificate_holder.address", label: "Adresă", code: "C.1.3", kind: "text", wide: true },
    ],
  },
  {
    id: "owner",
    title: "Proprietar (C.2)",
    note: "Proprietarul nu este presupus identic cu titularul. Completați doar dacă apare pe certificat.",
    fields: [
      { path: "vehicle.legal_owner.name", label: "Nume / denumire", code: "C.2.1+C.2.2", kind: "text", wide: true },
      { path: "vehicle.legal_owner.address", label: "Adresă", code: "C.2.3", kind: "text", wide: true },
    ],
  },
];

export const ALL_FIELDS: FieldDef[] = GROUPS.flatMap((g) => g.fields);
export const FIELD_BY_PATH: Record<string, FieldDef> = Object.fromEntries(ALL_FIELDS.map((f) => [f.path, f]));

export type FormValues = Record<string, string>;

export function getPath(obj: unknown, path: string): unknown {
  let cur: unknown = obj;
  for (const part of path.split(".")) {
    if (cur === null || cur === undefined || typeof cur !== "object") return null;
    cur = (cur as Record<string, unknown>)[part];
  }
  return cur ?? null;
}

export function toForm(p: Payload): FormValues {
  const out: FormValues = {};
  for (const f of ALL_FIELDS) {
    const v = getPath(p, f.path);
    out[f.path] = v === null || v === undefined ? "" : String(v);
  }
  return out;
}

const s = (v: string | undefined) => {
  const t = (v ?? "").trim();
  return t === "" ? null : t;
};
const n = (v: string | undefined) => {
  const t = (v ?? "").trim();
  return t === "" ? null : t; // backend parses & validates numbers
};

export function fromForm(values: FormValues, ownerPresent: boolean, docType: string | null) {
  const party = (prefix: string): Party | null => {
    const name = s(values[`${prefix}.name`]);
    const address = s(values[`${prefix}.address`]);
    return name || address ? { name, address } : null;
  };
  const person: Person = {
    first_name: s(values["person.first_name"]),
    last_name: s(values["person.last_name"]),
    national_id: s(values["person.national_id"]),
    identity_document: {
      type: docType,
      series: s(values["person.identity_document.series"]),
      number: s(values["person.identity_document.number"]),
      expiry_date: s(values["person.identity_document.expiry_date"]),
    },
    address: s(values["person.address"]),
  };
  const vehicle = {
    registration_number: s(values["vehicle.registration_number"]),
    vin: s(values["vehicle.vin"]),
    make: s(values["vehicle.make"]),
    model: s(values["vehicle.model"]),
    vehicle_type: s(values["vehicle.vehicle_type"]),
    category: s(values["vehicle.category"]),
    engine_cc: n(values["vehicle.engine_cc"]),
    power_kw: n(values["vehicle.power_kw"]),
    fuel: s(values["vehicle.fuel"]),
    first_registration: s(values["vehicle.first_registration"]),
    max_permissible_mass_kg: n(values["vehicle.max_permissible_mass_kg"]),
    seats: n(values["vehicle.seats"]),
    color: s(values["vehicle.color"]),
    certificate_holder: party("vehicle.certificate_holder"),
    legal_owner: ownerPresent ? party("vehicle.legal_owner") : null,
  } as unknown as Vehicle;
  return { person, vehicle };
}

// --- lightweight client-side hints (the backend remains the source of truth) ---

export function cnpHint(v: string): string | null {
  const d = v.replace(/\s/g, "");
  if (!d) return null;
  if (!/^\d{13}$/.test(d)) return "CNP trebuie să aibă 13 cifre.";
  const w = [2, 7, 9, 1, 4, 6, 3, 5, 8, 2, 7, 9];
  const sum = w.reduce((acc, wi, i) => acc + wi * Number(d[i]), 0);
  const rest = sum % 11;
  const c = rest === 10 ? 1 : rest;
  return c === Number(d[12]) ? null : "Cifra de control CNP nu corespunde.";
}

export function vinHint(v: string): string | null {
  const t = v.replace(/[\s-]/g, "").toUpperCase();
  if (!t) return null;
  if (t.length !== 17) return `VIN are ${t.length} caractere (necesar: 17).`;
  if (/[IOQ]/.test(t)) return "VIN nu poate conține I, O sau Q.";
  if (!/^[A-Z0-9]{17}$/.test(t)) return "VIN conține caractere nepermise.";
  return null;
}
