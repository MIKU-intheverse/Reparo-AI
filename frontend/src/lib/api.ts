const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("reparo_token");
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem("reparo_token", token);
  else window.localStorage.removeItem("reparo_token");
}

export function getEnvironment(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("reparo_env");
}

export function setEnvironment(env: string | null) {
  if (typeof window === "undefined") return;
  if (env) window.localStorage.setItem("reparo_env", env);
  else window.localStorage.removeItem("reparo_env");
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> | undefined),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${BASE_URL}${path}`, { ...options, headers });
  let body: any = null;
  try {
    body = await res.json();
  } catch {

  }
  if (!res.ok) {
    throw new ApiError(body?.detail || `Request failed (${res.status})`, res.status);
  }
  return body as T;
}

export const api = {

  signupStart: (email: string, environment: string) =>
    request<{ message: string }>("/api/auth/signup/start", {
      method: "POST",
      body: JSON.stringify({ email, environment }),
    }),
  signupVerify: (email: string, code: string) =>
    request<{ verified: boolean }>("/api/auth/signup/verify", {
      method: "POST",
      body: JSON.stringify({ email, code }),
    }),
  signupComplete: (email: string, password: string, environment: string) =>
    request<{ access_token: string; environment: string; email: string }>("/api/auth/signup/complete", {
      method: "POST",
      body: JSON.stringify({ email, password, environment }),
    }),
  signin: (email: string, password: string) =>
    request<{ access_token: string; environment: string; email: string }>("/api/auth/signin", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<{ email: string; environment: string; email_verified: boolean }>("/api/auth/me"),


  razorpayStatus: () =>
    request<{ connected: boolean; key_id: string | null; environment: string; status: string; last_synced_at: string | null }>(
      "/api/razorpay/status"
    ),
  razorpayConnect: (key_id: string, key_secret: string) =>
    request("/api/razorpay/connect", { method: "POST", body: JSON.stringify({ key_id, key_secret }) }),
  razorpayTestConnection: () => request("/api/razorpay/test-connection", { method: "POST" }),
  razorpayDisconnect: () => request("/api/razorpay/disconnect", { method: "POST" }),


  payments: (limit = 20, skip = 0, status?: string) =>
    request<{ items: any[]; count: number; has_more: boolean }>(
      `/api/payments?limit=${limit}&skip=${skip}${status ? `&status=${status}` : ""}`
    ),
  orders: (limit = 20, skip = 0) =>
    request<{ items: any[]; count: number; has_more: boolean }>(`/api/orders?limit=${limit}&skip=${skip}`),
  refunds: (limit = 20, skip = 0) =>
    request<{ items: any[]; count: number; has_more: boolean }>(`/api/refunds?limit=${limit}&skip=${skip}`),
  customers: (limit = 20, skip = 0) =>
    request<{ items: any[]; count: number; has_more: boolean }>(`/api/customers?limit=${limit}&skip=${skip}`),
  analytics: (days = 14) => request<any>(`/api/analytics?days=${days}`),
  search: (q: string) => request<{ items: any[]; count: number }>(`/api/search?q=${encodeURIComponent(q)}`),
  simulatePayment: (should_fail?: boolean) =>
    request<any>(`/api/simulate/payment${should_fail !== undefined ? `?should_fail=${should_fail}` : ""}`, {
      method: "POST",
    }),
  settlements: (limit = 20, skip = 0) =>
    request<{ items: any[]; count: number; has_more: boolean; unavailable?: boolean }>(
      `/api/settlements?limit=${limit}&skip=${skip}`
    ),
  disputes: (limit = 20, skip = 0) =>
    request<{ items: any[]; count: number; has_more: boolean; unavailable?: boolean }>(
      `/api/disputes?limit=${limit}&skip=${skip}`
    ),
  activity: (limit = 20) => request<{ items: any[] }>(`/api/activity?limit=${limit}`),
  webhooksRecent: (limit = 20) => request<{ items: any[] }>(`/api/webhooks/recent?limit=${limit}`),


  recoveryScan: () => request<{ new_or_updated_cases: number; case_ids: string[] }>("/api/recovery/scan", { method: "POST" }),
  recoveryCases: (status?: string, priority = false) =>
    request<{ items: any[]; count: number }>(
      `/api/recovery/cases?${status ? `status=${status}&` : ""}priority=${priority}`
    ),
  recoveryCase: (id: string) => request<any>(`/api/recovery/cases/${id}`),
  recoveryApprove: (id: string) => request<any>(`/api/recovery/cases/${id}/approve`, { method: "POST" }),
  recoveryReject: (id: string, reason: string) =>
    request<any>(`/api/recovery/cases/${id}/reject`, { method: "POST", body: JSON.stringify({ reason }) }),
  recoveryMetrics: () => request<any>("/api/recovery/metrics"),
  recoveryConfig: () => request<any>("/api/recovery/config"),


  agentChat: (message: string, history: any[] = []) =>
    request<{ reply: string; tool_trace: any[]; environment: string }>("/api/agent/chat", {
      method: "POST",
      body: JSON.stringify({ message, history }),
    }),
};
