/**
 * Shared API client — Sprint 10
 * All fetch calls must go through this helper so VITE_API_URL is respected.
 */

export const BASE_URL = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");

export async function apiFetch(path: string, options?: RequestInit): Promise<Response> {
  const url = path.startsWith("http") ? path : `${BASE_URL}${path}`;
  return fetch(url, options);
}
