// src/components/PostForm.tsx
import React, { useEffect, useRef } from "react";
import { apiFetch } from "../lib/api";

type PostType = "text" | "media" | "link";

interface PostFormProps {
  postType: PostType;
  title: string;
  setTitle: (v: string) => void;
  body: string;
  setBody: (v: string) => void;
  context: string;
  setContext: (v: string) => void;
  contextFocused: boolean;
  setContextFocused: (v: boolean) => void;
  onContextFocus: () => void;
  onContextBlur: () => void;
  link: string;
  setLink: (v: string) => void;
  postFiles: File[];
  setPostFiles: (files: File[]) => void;
  fileInputRef: React.RefObject<HTMLInputElement>;
  handleClearFiles: () => void;
  loading: boolean;
  onSubmit: (e: React.FormEvent) => void;
  error: string;
  contextExample: string;
}

/* If your post-type tabs are rendered inside this component,
   place this just above them:
   <h2 className="text-xl font-semibold mb-3">1. Select post type</h2>
*/

const inputBase =
  "w-full rounded-xl border border-gray-300 bg-white px-4 py-3 text-gray-900 placeholder-gray-400 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500";
const labelBase = "block text-sm font-medium text-gray-700";

function deriveTitleFromUrl(raw: string): string {
  try {
    const u = new URL(raw.trim());
    const qpCandidates = ["title", "subject", "headline"];
    for (const key of qpCandidates) {
      const v = u.searchParams.get(key);
      if (v) return decodeURIComponent(v).trim();
    }
    const host = u.hostname.replace(/^www\./i, "");
    const segments = u.pathname.split("/").filter(Boolean);
    let base = segments.length ? segments[segments.length - 1] : host;
    base = base.replace(/\.[a-z0-9]{2,4}$/i, "");
    base = base.replace(/[-_]+/g, " ");
    base = decodeURIComponent(base);
    const words = base.split(/\s+/).filter(Boolean);
    const titled =
      words.length > 0
        ? words.map((w) => (w[0] ? w[0].toUpperCase() + w.slice(1) : w)).join(" ")
        : host;
    return titled.trim();
  } catch {
    return "";
  }
}

export default function PostForm({
  postType,
  title,
  setTitle,
  body,
  setBody,
  context,
  setContext,
  onContextFocus,
  onContextBlur,
  link,
  setLink,
  postFiles,
  setPostFiles,
  fileInputRef,
  handleClearFiles,
  loading,
  onSubmit,
  error,
  contextExample,
}: PostFormProps) {
  const lastAutoTitleRef = useRef<string>("");
  const onFilesChange: React.ChangeEventHandler<HTMLInputElement> = (e) => {
    const files = Array.from(e.target.files ?? []);
    setPostFiles(files as File[]);
  };

  // Debounced metadata fetch → set Title from real page <meta> when Link tab is active
  useEffect(() => {
    if (postType !== "link") return;
    const trimmed = link.trim();
    if (!trimmed) return;

    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const res = await apiFetch(`/api/link_metadata?url=${encodeURIComponent(trimmed)}`);
        if (!res.ok) throw new Error("meta fetch failed");
        const data = await res.json();
        const metaTitle = (data.title || "").trim();

        const candidate = metaTitle || deriveTitleFromUrl(trimmed);
        if (!candidate || cancelled) return;

        const current = (title || "").trim();
        const lastAuto = lastAutoTitleRef.current;

        if (!current || current === lastAuto) {
          setTitle(candidate);
          lastAutoTitleRef.current = candidate;
        }
      } catch {
        const candidate = deriveTitleFromUrl(trimmed);
        const current = (title || "").trim();
        const lastAuto = lastAutoTitleRef.current;
        if (candidate && (!current || current === lastAuto) && !cancelled) {
          setTitle(candidate);
          lastAutoTitleRef.current = candidate;
        }
      }
    }, 400);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [link, postType]); // intentionally exclude title from deps

  const isLink = postType === "link";
  const isMedia = postType === "media";

  // Step numbering for the “Title & Body” block
  const titleBodyStepNumber = isLink ? 3 : 2;

  // Tab-specific heading that goes directly ABOVE the Context textarea and UNDER Body
  const contextStepHeading =
    postType === "text"
      ? "3. Describe your target subreddit (optional)"
      : "4. Describe your target subreddit (optional)";

  return (
    <form onSubmit={onSubmit} className="space-y-6">
      {/* LINK TAB: Link URL goes first */}
      {isLink && (
        <div>
          <h2 className="pt-2 text-xl font-semibold">2. Add a link</h2>
          <label htmlFor="post-link" className={labelBase}>
            Link URL
          </label>
          <input
            id="post-link"
            type="url"
            className={`${inputBase} mt-2`}
            placeholder="https://example.com/your-link"
            value={link}
            onChange={(e) => setLink(e.target.value)}
            autoComplete="off"
          />
        </div>
      )}

      {/* Title & Body */}
      <h2 className="text-xl font-semibold">
        {titleBodyStepNumber}. Write your post (Title &amp; Body)
      </h2>

      <div>
        <label htmlFor="post-title" className={labelBase}>
          Title
        </label>
        <input
          id="post-title"
          type="text"
          className={`${inputBase} mt-2`}
          placeholder="Enter a descriptive title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          autoComplete="off"
        />
      </div>

      <div>
        <label htmlFor="post-body" className={labelBase}>
          Body
        </label>
        <textarea
          id="post-body"
          className={`${inputBase} mt-2 min-h-[140px]`}
          placeholder="Write your post body"
          value={body}
          onChange={(e) => setBody(e.target.value)}
        />
      </div>

      {/* IMAGES TAB extra step before Context */}
      {isMedia && (
        <div>
          <h2 className="text-xl font-semibold mb-3">3. Upload images</h2>
          <label className={labelBase}>Images</label>
          <div className="mt-2 flex items-center gap-3">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              multiple
              onChange={onFilesChange}
              className="block w-full text-sm text-gray-700 file:mr-4 file:rounded-lg file:border-0 file:bg-indigo-600 file:px-4 file:py-2 file:text-white hover:file:bg-indigo-700"
            />
            {postFiles.length > 0 && (
              <button
                type="button"
                onClick={handleClearFiles}
                className="rounded-lg border px-3 py-2 text-sm"
              >
                Clear
              </button>
            )}
          </div>
        </div>
      )}

      {/* === Context heading goes RIGHT ABOVE the Context textarea and AFTER Body === */}
      <h2 className="pt-2 text-xl font-semibold">{contextStepHeading}</h2>

      <div>
        <label htmlFor="post-context" className={labelBase}>
          Context
        </label>
        <textarea
          id="post-context"
          className={`${inputBase} mt-2 min-h-[120px]`}
          placeholder={contextExample}
          value={context}
          onChange={(e) => setContext(e.target.value)}
          onFocus={onContextFocus}
          onBlur={onContextBlur}
        />
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
          {error}
        </div>
      )}

      {/* Submit */}
      <div className="pt-2">
        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-xl bg-indigo-600 px-5 py-3 font-semibold text-white shadow-md transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-70"
        >
          {loading ? "Finding…" : "Find a Subreddit"}
        </button>
      </div>
    </form>
  );
}
