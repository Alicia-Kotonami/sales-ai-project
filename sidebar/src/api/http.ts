import type { Envelope } from "./types";

const BASE = import.meta.env.VITE_API_BASE || "";

export class ApiError extends Error {
  readonly code: number;
  readonly traceId?: string;

  constructor(code: number, message: string, traceId?: string) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.traceId = traceId;
  }
}

export function getToken(): string | null {
  return sessionStorage.getItem("salesai.sidebar.token");
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  let body: Envelope<T>;
  try {
    body = (await res.json()) as Envelope<T>;
  } catch {
    throw new ApiError(9999, `HTTP ${res.status}`);
  }
  if (body.code === 1002) {
    sessionStorage.removeItem("salesai.sidebar.token");
    sessionStorage.removeItem("salesai.sidebar.user");
  }
  if (body.code !== 0) {
    throw new ApiError(body.code, body.message || "请求失败", body.trace_id);
  }
  return body.data;
}
