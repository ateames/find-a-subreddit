// src/components/AddSubreddit.tsx
import React, { useCallback, useMemo, useState } from "react";
import { apiFetch } from "../lib/api";

/**
 * ---- API CONTRACT (adjust if your backend differs) ----
 * GET  /api/subreddits/:name
 *   200 -> { name, title?, description?, subscribers?, ai_summary?, icon_img?, banner_img?, rules?, vibe? }
 *   404 -> not found
 *
 * POST /api/ingest/subreddit  JSON: { name: string }
 *   200 -> same shape as above (newly added/ingested)
 *   409 -> already exists (treat as "exists")
 */

type Vibe = {
  beginner_friendly?: number; // 0-100
  strictness?: number;        // 0-100
  meme_tolerance?: number;    // 0-100
};

export interface Subreddit {
  name: string;               // bare name, e.g., "askscience"
  title?: string;
  description?: string;
  subscribers?: number;
  ai_summary?: string;
  icon_img?: string;
  banner_img?: string;
  rules?: string[];
  vibe?: Vibe;
}

type Status = "idle" | "checking" | "exists" | "adding" | "added" | "error";

export interface AddSubredditProps {
  /** Optional: custom renderer for a subreddit card (use your existing card) */
  renderCard?: (sub: Subreddit) => React.ReactNode;
  /** Optional: callback when a subreddit has been located/added */
  onResolved?: (sub: Subreddit, existed: boolean) => void;
  /** Optional initial value in the input (e.g., when wiring from elsewhere) */
  defaultValue?: string;
  /** Optional: override endpoints if your routes differ */
  endpoints?: {
    check: (normalizedName: string) => string; // e.g., (n) => `/api/subreddits/${n}`
    add: string; // e.g., "/api/ingest/subreddit"
  };
}

/** Utility: commas 1,234,567 */
function formatInt(n?: number) {
  if (typeof n !== "number") return undefined;
  try {
    return n.toLocaleString();
  } catch {
    return String(n);
  }
}

/** Basic subreddit name validation: 3–21 chars, letters, numbers, underscore */
function normalizeAndValidate(input: string): { valid: boolean; name?: string; reason?: string } {
  const trimmed = input.trim();
  // Accept "r/foo", "/r/foo", or "foo"
  const stripped = trimmed
    .replace(/^\/?r\//i, "")
    .trim();

  const name = stripped; // keep original case for display; Reddit is case-insensitive
  if (!name) return { valid: false, reason: "Enter a subreddit name." };

  // Reddit: letters, numbers, underscores; 3–21 chars
  if (!/^[A-Za-z0-9_]{3,21}$/.test(name)) {
    return {
      valid: false,
      reason: "Use 3–21 letters, numbers, or underscores (no spaces or hyphens).",
    };
  }
  return { valid: true, name };
}

/** Small, neat loader */
function Spinner() {
  return (
    <svg
      className="h-5 w-5 animate-spin"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" opacity="0.25" />
      <path d="M22 12a10 10 0 0 1-10 10" stroke="currentColor" strokeWidth="4" fill="none" />
    </svg>
  );
}

/** A clean, built-in fallback card if you don't pass renderCard */
function FallbackSubredditCard({ sub }: { sub: Subreddit }) {
  return (
    <div className="w-full rounded-2xl border bg-white p-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
      <div className="flex items-center gap-3">
        {sub.icon_img ? (
          <img
            src={sub.icon_img}
            alt={`${sub.name} icon`}
            className="h-10 w-10 rounded-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="h-10 w-10 rounded-full bg-gray-200 dark:bg-neutral-800" />
        )}
        <div>
          <div className="text-lg font-semibold">r/{sub.name}</div>
          {!!sub.title && <div className="text-sm text-gray-500 dark:text-gray-400">{sub.title}</div>}
        </div>
      </div>

      {!!sub.ai_summary && (
        <p className="mt-3 text-sm leading-relaxed text-gray-800 dark:text-gray-200">
          {sub.ai_summary}
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-gray-600 dark:text-gray-300">
        {typeof sub.subscribers === "number" && (
          <span className="rounded-full border px-2 py-0.5 dark:border-neutral-700">
            {formatInt(sub.subscribers)} members
          </span>
        )}
        {sub.vibe?.beginner_friendly !== undefined && (
          <span className="rounded-full border px-2 py-0.5 dark:border-neutral-700">
            Beginner-friendly: {sub.vibe.beginner_friendly}
          </span>
        )}
        {sub.vibe?.strictness !== undefined && (
          <span className="rounded-full border px-2 py-0.5 dark:border-neutral-700">
            Strictness: {sub.vibe.strictness}
          </span>
        )}
        {sub.vibe?.meme_tolerance !== undefined && (
          <span className="rounded-full border px-2 py-0.5 dark:border-neutral-700">
            Meme tolerance: {sub.vibe.meme_tolerance}
          </span>
        )}
      </div>

      {!!sub.rules?.length && (
        <details className="mt-4 group">
          <summary className="cursor-pointer select-none text-sm font-medium group-open:mb-2">
            Rules
          </summary>
          <ul className="list-disc pl-5 text-sm leading-relaxed">
            {sub.rules.slice(0, 8).map((r, i) => (
              <li key={i} className="mt-1">{r}</li>
            ))}
            {sub.rules.length > 8 && <li className="mt-1 italic">…and more</li>}
          </ul>
        </details>
      )}
    </div>
  );
}

export default function AddSubreddit({
  renderCard,
  onResolved,
  defaultValue,
  endpoints,
}: AddSubredditProps) {
  const [input, setInput] = useState(defaultValue ?? "");
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Subreddit | null>(null);
  const [existed, setExisted] = useState(false);

  const ep = useMemo(
    () => ({
      check: endpoints?.check ?? ((n: string) => `/api/subreddits/${encodeURIComponent(n)}`),
      add: endpoints?.add ?? "/api/ingest/subreddit",
    }),
    [endpoints]
  );

  const doCheck = useCallback(async (name: string): Promise<Subreddit | null> => {
    const res = await apiFetch(ep.check(name));
    if (res.ok) return (await res.json()) as Subreddit;
    if (res.status === 404) return null;
    // In case backend returns helpful error JSON
    let msg = "Unable to check subreddit.";
    try {
      const text = await res.text();
      msg = text || msg;
    } catch {}
    throw new Error(msg);
  }, [ep]);

  const doAdd = useCallback(async (name: string): Promise<Subreddit> => {
    const res = await apiFetch(ep.add, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (res.ok) return (await res.json()) as Subreddit;
    if (res.status === 409) {
      // Treat conflict as "exists" — try to fetch canonical record
      const existing = await doCheck(name);
      if (existing) return existing;
    }
    let msg = "Unable to add subreddit.";
    try {
      const text = await res.text();
      msg = text || msg;
    } catch {}
    throw new Error(msg);
  }, [doCheck, ep]);

  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setResult(null);
    setExisted(false);

    const { valid, name, reason } = normalizeAndValidate(input);
    if (!valid || !name) {
      setError(reason ?? "Invalid subreddit name.");
      setStatus("error");
      return;
    }

    setStatus("checking");
    try {
      const found = await doCheck(name);
      if (found) {
        setResult(found);
        setExisted(true);
        setStatus("exists");
        onResolved?.(found, true);
        return;
      }
      setStatus("adding");
      const added = await doAdd(name);
      setResult(added);
      // If backend returned an already-existing record via 409 path:
      const wasExisting = await doCheck(name);
      const existedNow = !!wasExisting;
      setExisted(existedNow);
      setStatus(existedNow ? "exists" : "added");
      onResolved?.(added, existedNow);
    } catch (err: any) {
      setError(err?.message || "Something went wrong.");
      setStatus("error");
    }
  }, [doAdd, doCheck, input, onResolved]);

  // ---- Derived state ----
  const isBusy = status === "checking" || status === "adding";
  const canSubmit =
    input.trim().length > 0 &&
    (status === "idle" || status === "error" || status === "exists" || status === "added");

  return (
    <div className="w-full max-w-2xl mx-auto">
      <div className="rounded-2xl border bg-white p-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
        <h2 className="text-xl font-semibold">Add a Subreddit</h2>
        <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">
          Enter a subreddit to add it to Find A Subreddit. We’ll check if it already exists first.
        </p>

        <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-3">
          <label htmlFor="subreddit-input" className="text-sm font-medium">
            Subreddit name
          </label>
          <div className="flex items-center gap-2">
            <span className="rounded-lg border bg-gray-50 px-2 py-2 text-gray-500 dark:border-neutral-700 dark:bg-neutral-800 dark:text-gray-300">
              r/
            </span>
            <input
              id="subreddit-input"
              name="subreddit"
              type="text"
              spellCheck={false}
              autoComplete="off"
              placeholder="askscience"
              className="flex-1 rounded-lg border px-3 py-2 outline-none focus:ring-2 focus:ring-black/10 dark:border-neutral-700 dark:bg-neutral-800"
              value={input.replace(/^\/?r\//i, "")}
              onChange={(e) => setInput(e.target.value)}
              aria-invalid={status === "error" ? true : undefined}
            />
            <button
              type="submit"
              disabled={!canSubmit || isBusy}
              className="inline-flex items-center gap-2 rounded-xl bg-black px-4 py-2 text-white disabled:opacity-50 dark:bg-white dark:text-black"
            >
              {isBusy ? <Spinner /> : null}
              {status === "adding" ? "Adding…" : status === "checking" ? "Checking…" : "Add"}
            </button>
          </div>
          {status === "error" && !!error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-300">
              {error}
            </div>
          )}
        </form>
      </div>

      {result && (
        <div className="mt-4 space-y-3">
          <div
            className={`rounded-xl px-3 py-2 text-sm ${
              existed
                ? "border border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-200"
                : "border border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-200"
            }`}
          >
            {existed ? (
              <>r/{result.name} is already in Find A Subreddit. Showing the current record.</>
            ) : (
              <>r/{result.name} has been added to Find A Subreddit. Here’s the new AI summary & details.</>
            )}
          </div>

          <div>
            {renderCard ? (
              renderCard(result)
            ) : (
              <FallbackSubredditCard sub={result} />
            )}
          </div>

          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => {
                setInput("");
                setStatus("idle");
                setResult(null);
                setExisted(false);
                setError(null);
              }}
              className="rounded-lg border px-3 py-2 text-sm dark:border-neutral-700"
            >
              Add another
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
