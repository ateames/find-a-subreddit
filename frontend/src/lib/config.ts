// src/lib/config.ts
const rawApiUrl = import.meta.env.VITE_API_URL?.trim();

if (!rawApiUrl) {
  throw new Error(
    "VITE_API_URL is not set. Define it in DO (frontend component) and .env files."
  );
}

// Normalize (no trailing slash)
export const API_URL = rawApiUrl.replace(/\/+$/, "");

// --- Query override: ?showTestSub=1|0 (also accepts true/false/yes/no/on/off) ---
const parseBool = (v: string | null | undefined): boolean | null => {
  if (v == null) return null;
  const s = String(v).trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(s)) return true;
  if (["0", "false", "no", "off"].includes(s)) return false;
  return null;
};

const getQueryBool = (name: string): boolean | null => {
  if (typeof window === "undefined") return null;
  try {
    const params = new URLSearchParams(window.location.search);
    return parseBool(params.get(name));
  } catch {
    return null;
  }
};

const qpShowTestSub = getQueryBool("showTestSub");

// Env default (preserves existing behavior if no query param)
const envShowTestSub =
  String(import.meta.env.VITE_SHOW_TEST_SUB ?? "false").toLowerCase() === "true";

// Final flags
export const SHOW_TEST_SUB = qpShowTestSub ?? envShowTestSub;
// Keep Debug in lockstep with SHOW_TEST_SUB per requirement
export const SHOW_DEBUG = SHOW_TEST_SUB;

// Quick runtime log (visible in browser devtools)
if (import.meta.env.MODE !== "production") {
  // eslint-disable-next-line no-console
  console.log("[config]", { API_URL, SHOW_TEST_SUB, SHOW_DEBUG });
}
