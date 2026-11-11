import type { ApiErrorBody, Health, Payload, SampleSet } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: ApiErrorBody,
  ) {
    super(body.message);
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (res.ok) return (await res.json()) as T;
  let body: ApiErrorBody;
  try {
    const json = await res.json();
    body = json.error ?? { code: "HTTP_" + res.status, message: res.statusText };
  } catch {
    body = {
      code: "HTTP_" + res.status,
      message:
        res.status === 502 || res.status === 504
          ? "Serverul backend nu răspunde. Porniți API-ul (vezi README)."
          : `Eroare HTTP ${res.status}`,
    };
  }
  throw new ApiError(res.status, body);
}

async function request<T>(input: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(input, init);
  } catch {
    throw new ApiError(0, {
      code: "NETWORK_ERROR",
      message: "Nu se poate contacta serverul backend. Verificați că rulează pe portul 8000.",
    });
  }
  return handle<T>(res);
}

export const api = {
  health: () => request<Health>("/api/v1/health"),
  samples: () => request<{ synthetic: boolean; sets: SampleSet[] }>("/api/v1/samples"),
  async sampleFile(name: string): Promise<File> {
    const res = await fetch(`/api/v1/samples/${encodeURIComponent(name)}`);
    if (!res.ok) throw new ApiError(res.status, { code: "SAMPLE_NOT_FOUND", message: "Fișier demo indisponibil." });
    const blob = await res.blob();
    return new File([blob], name, { type: blob.type });
  },
  extract(identity: File | null, registration: File | null, engine?: string): Promise<Payload> {
    const form = new FormData();
    if (identity) form.append("identity_image", identity);
    if (registration) form.append("registration_image", registration);
    const q = new URLSearchParams({ include_ocr_text: "true" });
    if (engine) q.set("engine", engine);
    return request<Payload>(`/api/v1/extract?${q}`, { method: "POST", body: form });
  },
  validate: (body: unknown) =>
    request<Payload>("/api/v1/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  confirm: (body: unknown) =>
    request<{ status: "confirmed"; payload: Payload }>("/api/v1/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  discard: (id: string) => fetch(`/api/v1/processing/${encodeURIComponent(id)}`, { method: "DELETE" }).catch(() => {}),
};
