// src/lib/api.ts
import { API_URL } from "./config";

function isAbsoluteUrl(u: string): boolean {
  try {
    new URL(u);
    return true;
  } catch {
    return false;
  }
}

/** Build a stable base URL object from absolute or relative API_URL */
function getApiBase(): URL {
  if (isAbsoluteUrl(API_URL)) {
    return new URL(API_URL.replace(/\/+$/, "")); // normalize trailing slash
  }
  // Relative base (e.g., "/"): resolve against current origin so api.origin works
  const origin =
    typeof window !== "undefined" ? window.location.origin : "http://localhost";
  const rel = API_URL || "/";
  return new URL(rel.replace(/\/+$/, "") || "/", origin);
}

export const api = getApiBase();

const join = (base: URL, path: string) =>
  new URL(path, base).toString();

/** Wrap fetch with the right base URL + credentials, safely handling FormData */
export async function apiFetch(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const url = join(api, path);

  // Build headers safely; don't force JSON for multipart/form-data
  const headers = new Headers(init.headers || {});
  const isFormData =
    typeof FormData !== "undefined" && init.body instanceof FormData;

  if (!headers.has("Content-Type") && !isFormData && init.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  return fetch(url, {
    credentials: "include", // keep Reddit auth cookie
    ...init,
    headers,
  });
}

/** Optional helper to produce a full API URL for logging/debug */
export const apiUrl = (path: string) => join(api, path);
