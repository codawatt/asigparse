export type Severity = "error" | "warning" | "info";
export type FieldStatus =
  | "extracted"
  | "missing"
  | "needs_review"
  | "not_on_document"
  | "corrected"
  | "confirmed"
  | "excluded";

export interface IdentityDocument {
  type: string | null;
  series: string | null;
  number: string | null;
  expiry_date: string | null;
}

export interface Person {
  first_name: string | null;
  last_name: string | null;
  national_id: string | null;
  identity_document: IdentityDocument;
  address: string | null;
}

export interface Party {
  name: string | null;
  address: string | null;
}

export interface Vehicle {
  registration_number: string | null;
  vin: string | null;
  make: string | null;
  model: string | null;
  vehicle_type: string | null;
  category: string | null;
  engine_cc: number | null;
  power_kw: number | null;
  fuel: string | null;
  first_registration: string | null;
  max_permissible_mass_kg: number | null;
  seats: number | null;
  color: string | null;
  certificate_holder: Party | null;
  legal_owner: Party | null;
}

export interface FieldMeta {
  source: string | null;
  confidence: number | null;
  review_required: boolean;
  status: FieldStatus;
  reason: string | null;
  checks: string[];
}

export interface Issue {
  field: string;
  code: string;
  severity: Severity;
  message: string | null;
  suggestion: string | null;
}

export interface DocumentInfo {
  slot: "identity" | "registration";
  file_type: string;
  detected_type: string;
  pages_processed: number;
  ocr_engine: string;
  ocr_mean_confidence: number | null;
  rotation_applied: number[];
  quality: { width: number; height: number; blur_score: number; brightness: number }[];
  warnings: string[];
  codes_found: string[] | null;
  ocr_text: string | null;
}

export interface Payload {
  schema_version: string;
  processing_id: string;
  status: "needs_review" | "ready_for_confirmation" | "confirmed";
  purpose: string;
  person: Person;
  vehicle: Vehicle;
  field_meta: Record<string, FieldMeta>;
  validation: { passed: boolean; issues: Issue[] };
  confirmed_by_operator: boolean;
  confirmed_at: string | null;
  documents: DocumentInfo[];
  processing_time_ms: number | null;
  disclaimer: string;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  document?: string | null;
  issues?: Issue[];
}

export interface SampleSet {
  id: string;
  title: string;
  description: string;
  identity: string;
  registration: string;
}

export interface Health {
  status: string;
  ocr: {
    engine: string;
    available: boolean;
    version: string | null;
    languages: string;
    missing_languages: string[];
  };
  engines: Record<string, { available: boolean; version: string | null; reason: string | null }>;
  confidence_threshold: number;
  max_upload_mb: number;
}
