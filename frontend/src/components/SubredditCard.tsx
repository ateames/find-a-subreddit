import React, { useState, useEffect, useRef } from "react";
import { Card, CardContent } from "./ui/card";
import { Accordion, AccordionItem, AccordionTrigger, AccordionContent } from "./ui/accordion";
import { Input } from "./ui/input";
import { Textarea } from "./ui/textarea";
import { apiFetch } from "../lib/api";

interface SubredditResult {
  subreddit: string;
  score?: number;
  description?: string;
  rules?: string[];
  ai_warning?: string[];
  subscribers?: number;

  // NEW (all optional to avoid breaking callers)
  content_types_not_allowed?: string[]; // e.g., ["images","links","memes"]
  summary?: string; // ≤15-word vibe sentence
  beginner_friendly_score?: number; // 0–5
  beginner?: number; // fallback if API uses 'beginner' from vibe table
}

interface RedditUser {
  name: string;
  icon_img?: string;
}

interface SubredditCardProps {
  sub: SubredditResult;
  abbreviateNumber: (value: number) => string;
  title: string;
  body: string;
  link: string;
  postType: "text" | "media" | "link";
  postingSub: string | null;
  setPostingSub: (v: string | null) => void;
  postTitle: string;
  setPostTitle: (v: string) => void;
  postBody: string;
  setPostBody: (v: string) => void;
  postError: string;
  setPostError: (v: string) => void;
  postLoading: boolean;
  handleSubmitToReddit: (e: React.FormEvent) => void;
  postConfirmations: { [sub: string]: string };
  postFiles: File[];
  handleClearFiles: () => void;
  fileInputRef: React.RefObject<HTMLInputElement>;
  onRequestPostToSubreddit: (subreddit: string) => void;
  user: RedditUser | null;
}

// ---- Flair types (unchanged) ----
type FlairRich =
  | { e: "text"; t: string }
  | { e: "emoji"; a?: string; u?: string }; // a=alias, u=image url

interface FlairOption {
  id: string;
  text: string;
  richtext: FlairRich[];
  text_color: "dark" | "light" | "";
  background_color: string;
  editable: boolean;
  css_class?: string;
}

const flairLabel = (f: FlairOption, idx?: number) => {
  if (f.text && f.text.trim()) return f.text;
  const s = (f.richtext || [])
    .map((r) =>
      r.e === "text" ? (r.t || "") : r.e === "emoji" ? (r.a ? `:${r.a}:` : "🔹") : ""
    )
    .join("");
  if (s.trim()) return s.trim();
  if (f.css_class && f.css_class.trim()) return `[${f.css_class}]`;
  return idx != null ? `Untitled flair #${idx + 1}` : "Untitled flair";
};

// ---- NEW: Beginner→Advanced meter helpers ----
const clamp = (n: number, min: number, max: number) => Math.max(min, Math.min(max, n));

const getBeginnerScore = (sub: SubredditResult): number | null => {
  const raw = sub.beginner_friendly_score ?? sub.beginner;
  if (raw === undefined || raw === null) return null;
  // Accept floats but clamp and round to nearest segment
  return Math.round(clamp(Number(raw), 0, 5));
};

const SEGMENT_COLORS = ["bg-green-500", "bg-lime-500", "bg-yellow-400", "bg-orange-400", "bg-red-500"];

// ---- NEW: Restrictions → emoji mapping ----
const RESTRICTION_EMOJI: Record<string, { emoji: string; label: string }> = {
  images: { emoji: "🖼️ Images", label: "Images not allowed" },
  image: { emoji: "🖼️ Images", label: "Images not allowed" },
  videos: { emoji: "🎥 Video", label: "Videos not allowed" },
  video: { emoji: "🎥 Video", label: "Videos not allowed" },
  links: { emoji: "🔗 Links", label: "Links not allowed" },
  link: { emoji: "🔗 Links", label: "Links not allowed" },
  polls: { emoji: "📊 Polls", label: "Polls not allowed" },
  memes: { emoji: "🤣 Memes", label: "Memes not allowed" },
  self_promo: { emoji: "📣 Self-promo", label: "Self-promo not allowed" },
  selfpromo: { emoji: "📣 Self-promo", label: "Self-promo not allowed" },
  advertising: { emoji: "📢 Ads", label: "Ads not allowed" },
  nsfw: { emoji: "🔞 NSFW", label: "NSFW not allowed" },
  NSFW: { emoji: "🔞 NSFW", label: "NSFW not allowed" },
  ai: { emoji: "🤖 AI", label: "AI content not allowed" },
  AI: { emoji: "🤖 AI", label: "AI content not allowed" },
  screenshots: { emoji: "📱 Screenshots", label: "Screenshots not allowed" },
  survey: { emoji: "📝 Surveys", label: "Surveys not allowed" },
  spam: { emoji: "🚫 Spam", label: "Spam not allowed" },
  reposts: { emoji: "🔄 Reposts", label: "Reposts not allowed" },
  low_effort: { emoji: "🥱 Low-effort", label: "Low-effort posts not allowed" },
  off_topic: { emoji: "🚫 Off-topic", label: "Off-topic not allowed" },
};

const normalizeRestrictionKey = (s: string) =>
  s.trim().toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, "");

const SubredditCard: React.FC<SubredditCardProps> = ({
  sub,
  abbreviateNumber,
  title,
  body,
  link,
  postType,
  postingSub,
  setPostingSub,
  postTitle,
  setPostTitle,
  postBody,
  setPostBody,
  postError,
  setPostError,
  postLoading,
  handleSubmitToReddit,
  postConfirmations,
  postFiles,
  handleClearFiles,
  fileInputRef,
  onRequestPostToSubreddit,
  user,
}) => {
  // Flair/tag UI state
  const [flairOptions, setFlairOptions] = useState<FlairOption[]>([]);
  const [flairLoading, setFlairLoading] = useState(false);
  const [flairError, setFlairError] = useState<string | null>(null);

  const [showFlairDropdown, setShowFlairDropdown] = useState(false);
  const [selectedFlair, setSelectedFlair] = useState<string | null>(null);
  const [selectedTags, setSelectedTags] = useState({ nsfw: false, brand: false });

  const abortRef = useRef<AbortController | null>(null);

  // Reset flair state when switching which sub is "open" for posting
  useEffect(() => {
    if (postingSub !== sub.subreddit) {
      setShowFlairDropdown(false);
      setFlairOptions([]);
      setFlairError(null);
      setSelectedFlair(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [postingSub, sub.subreddit]);

  const fetchFlair = async () => {
    // cancel any previous in-flight request
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setFlairLoading(true);
    setFlairError(null);
    try {
      const res = await apiFetch(
        `/api/reddit/flair_options?r=${encodeURIComponent(sub.subreddit)}`,
        { signal: controller.signal }
      );

      let payload: any = null;
      try {
        payload = await res.json();
      } catch {
        /* ignore JSON parse errors */
      }

      // DEBUG (optional)
      console.debug("[flair_options] status", res.status, res.statusText);
      console.debug("[flair_options] raw payload", payload);

      if (!res.ok) {
        const detail = payload?.detail || payload?.error || res.statusText;
        if (res.status === 403) {
          throw new Error("This subreddit requires membership to view user-selectable flair.");
        }
        if (res.status === 404) {
          throw new Error("Subreddit not found.");
        }
        throw new Error(detail || "Could not load flair options");
      }

      const flairList: FlairOption[] = Array.isArray(payload?.flair) ? payload.flair : [];

      // Filter/normalize and sort by human label
      const normalized = flairList
        .filter((f) => !!f.id)
        .map((f) => ({ ...f, text: f.text ?? "", richtext: f.richtext ?? [] }));

      normalized.sort((a, b) =>
        flairLabel(a).localeCompare(flairLabel(b), undefined, { sensitivity: "base" })
      );

      // DEBUG (optional)
      console.debug("[flair_options] normalized", normalized);

      setFlairOptions(normalized);

      // Keep previous selection if still present; else preselect if only one option
      setSelectedFlair((prev) =>
        normalized.some((f) => f.id === prev)
          ? prev
          : normalized.length === 1
          ? normalized[0].id
          : null
      );
    } catch (err: any) {
      if (err?.name === "AbortError") return;
      setFlairError(err?.message || "Failed to load flair options");
    } finally {
      setFlairLoading(false);
    }
  };

  // Optionally prefetch flair when the posting UI opens for this sub
  useEffect(() => {
    if (user && postingSub === sub.subreddit && showFlairDropdown && flairOptions.length === 0 && !flairLoading) {
      fetchFlair();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, postingSub, sub.subreddit, showFlairDropdown]);

  // Fetch flair options (if not loaded) when user clicks "Add flair and tags"
  const handleOpenFlair = async () => {
    setShowFlairDropdown((open) => !open);
    const willOpen = !showFlairDropdown;
    if (willOpen && flairOptions.length === 0 && !flairLoading) {
      fetchFlair();
    }
  };

  // Handle tag toggle
  const toggleTag = (tag: "nsfw" | "brand") =>
    setSelectedTags((prev) => ({ ...prev, [tag]: !prev[tag] }));

  // Attach flair/tag to global (window) for parent to pick up in FormData
  const handlePostSubmit = (e: React.FormEvent) => {
    (window as any).__selectedFlair = selectedFlair;
    (window as any).__selectedTags = selectedTags;
    handleSubmitToReddit(e);
  };

  // ---- Derived UI data (NEW sections) ----
  const beginnerScore = getBeginnerScore(sub);
  const hasRestrictions =
    Array.isArray(sub.content_types_not_allowed) && sub.content_types_not_allowed.length > 0;

  const restrictionBadges =
    (sub.content_types_not_allowed || []).map((raw, idx) => {
      const key = normalizeRestrictionKey(String(raw));
      const entry = RESTRICTION_EMOJI[key] || { emoji: "🚫", label: raw };
      return (
        <span
          key={`${key}-${idx}`}
          title={entry.label}
          className="select-none text-lg leading-none"
          aria-label={entry.label}
        >
          {entry.emoji}
        </span>
      );
    });

  return (
    <Card className="rounded-2xl shadow p-4">
      <CardContent className="p-0">
        <div className="flex flex-col gap-2">
          {sub.subreddit === "test" && (
            <div className="mb-2 p-2 bg-yellow-100 border-l-4 border-yellow-400 text-yellow-900 font-semibold rounded">
              Use r/test to test posting.
            </div>
          )}
          <a
            href={`https://www.reddit.com/r/${sub.subreddit}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-lg font-bold text-blue-700 hover:underline"
          >
            r/{sub.subreddit}
          </a>

          {/* Meta: members + match */}
          <div className="flex items-center gap-4 text-gray-500 text-sm">
            {typeof sub.subscribers === "number" && (
              <span>
                <span className="font-semibold">Members:</span>{" "}
                {abbreviateNumber(sub.subscribers)}
              </span>
            )}
            <span>
              <span className="font-semibold">Match:</span>{" "}
              {Math.round((sub.score || 0) * 100)}%
            </span>
          </div>

          {/* Description (existing) */}
          <div className="text-gray-700 mt-2">{sub.description}</div>

          {/* NEW: AI Summary */}
          {sub.summary && (
            <div className="mt-1 text-gray-700">
              <span className="font-semibold">AI Summary:</span>{" "}
              <span className="italic">{sub.summary}</span>
            </div>
          )}

          {/* NEW: Beginner → Advanced meter */}
          {beginnerScore !== null && (
            <div className="mt-2">
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-500">Beginner</span>
                <div
                  className="flex gap-1"
                  role="progressbar"
                  aria-label="Beginner to Advanced"
                  aria-valuemin={0}
                  aria-valuemax={5}
                  aria-valuenow={beginnerScore}
                >
                  {Array.from({ length: 5 }).map((_, i) => {
                    const filled = i < beginnerScore;
                    const color = filled ? SEGMENT_COLORS[i] : "bg-gray-200";
                    return (
                      <div
                        key={i}
                        className={`h-2 w-6 rounded ${color}`}
                        title={`${beginnerScore}/5`}
                      />
                    );
                  })}
                </div>
                <span className="text-xs text-gray-500">Advanced</span>
                <span className="text-xs text-gray-400 ml-2">({beginnerScore}/5)</span>
              </div>
            </div>
          )}

          {/* NEW: Restrictions (emojis) */}
          {hasRestrictions && (
            <div className="mt-2 flex items-center gap-2 text-sm">
              <span className="font-semibold">Restrictions:</span>
              <div className="flex flex-wrap gap-2 text-xs leading-tight">
                {restrictionBadges}
              </div>
            </div>
          )}

          {/* Rules + Possible violations */}
          <Accordion type="single" collapsible>
            <AccordionItem value="rules">
              <AccordionTrigger>
                <span>r/{sub.subreddit} Rules</span>
              </AccordionTrigger>
              <AccordionContent>
                <ul className="list-disc pl-6 space-y-1">
                  {(sub.rules || []).map((rule, i) => (
                    <li key={i} className="whitespace-pre-line">
                      {rule}
                    </li>
                  ))}
                </ul>
              </AccordionContent>
            </AccordionItem>

            {sub.ai_warning && sub.ai_warning.length > 0 && (
              <AccordionItem value="ai_warning">
                <AccordionTrigger>
                  <span>⚠️❗Possible Rule Violations</span>
                </AccordionTrigger>
                <AccordionContent>
                  <ul className="list-disc pl-6 space-y-1">
                    {sub.ai_warning.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                </AccordionContent>
              </AccordionItem>
            )}
          </Accordion>

          {/* Post confirmation */}
          {postConfirmations[sub.subreddit] && (
            <div className="bg-green-100 text-green-700 px-4 py-2 rounded mb-2 mt-2 text-center">
              Post submitted!&nbsp;
              <a
                href={postConfirmations[sub.subreddit]}
                target="_blank"
                rel="noopener noreferrer"
                className="underline text-blue-700"
              >
                View on Reddit
              </a>
            </div>
          )}

          {/* Actions */}
          <div className="flex mt-4 gap-2">
            <button
              className="bg-orange-600 text-white px-4 py-2 rounded-md hover:bg-orange-700 transition"
              onClick={() => {
                onRequestPostToSubreddit(sub.subreddit);
                setPostTitle(title);
                setPostBody(body);
                setPostError("");
                // Reset flair/tag globals when opening post
                (window as any).__selectedFlair = "";
                (window as any).__selectedTags = {};
              }}
            >
              Post to r/{sub.subreddit}
            </button>
            {/* Only show Add Flair if user is authenticated and posting UI is open for this sub */}
            {user && postingSub === sub.subreddit && (
              <button
                className="bg-gray-100 border px-3 rounded hover:bg-gray-200 text-sm"
                onClick={handleOpenFlair}
                type="button"
              >
                {showFlairDropdown ? "Hide flair/tags" : "Add flair and tags"}
              </button>
            )}
          </div>

          {/* Flair/Tag UI */}
          {user && showFlairDropdown && postingSub === sub.subreddit && (
            <div className="mt-2 mb-2 bg-gray-50 border rounded p-3">
              {flairLoading ? (
                <div>Loading flair…</div>
              ) : flairError ? (
                <div className="text-red-600">{flairError}</div>
              ) : flairOptions.length === 0 ? (
                <div className="text-sm text-gray-600">No user-selectable link flair in this subreddit.</div>
              ) : (
                <div className="flex flex-col gap-2">
                  <label className="font-semibold">Choose Flair:</label>
                  <select
                    className="border rounded p-1"
                    value={selectedFlair || ""}
                    onChange={(e) => setSelectedFlair(e.target.value || null)}
                  >
                    <option value="">No flair</option>
                    {flairOptions.map((flair, idx) => (
                      <option value={flair.id} key={`${flair.id}-${idx}`}>
                        {flairLabel(flair, idx)}
                      </option>
                    ))}
                  </select>
                  {/* optional visual chip for selected flair color */}
                  {selectedFlair && (
                    <div className="flex items-center gap-2 text-xs">
                      {(() => {
                        const f = flairOptions.find((o) => o.id === selectedFlair);
                        if (!f) return null;
                        return (
                          <>
                            <span>Preview:</span>
                            <span
                              className="px-2 py-0.5 rounded flex items-center gap-1"
                              style={{
                                backgroundColor: f.background_color || "transparent",
                                color: f.text_color === "light" ? "#fff" : "#111",
                                border: "1px solid rgba(0,0,0,0.1)",
                              }}
                            >
                              {(f.richtext || []).map((r, i) =>
                                r.e === "text" ? (
                                  <span key={i}>{r.t}</span>
                                ) : (
                                  <img
                                    key={i}
                                    src={r.u}
                                    alt={r.a || "emoji"}
                                    className="inline-block h-4 w-4"
                                  />
                                )
                              )}
                              {!f.richtext?.length && (f.text || "(no text)")}
                            </span>
                          </>
                        );
                      })()}
                    </div>
                  )}
                  <div className="flex gap-4 mt-2">
                    <label className="flex items-center gap-1 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={selectedTags.nsfw}
                        onChange={() => toggleTag("nsfw")}
                        className="accent-orange-600"
                      />
                      NSFW
                    </label>
                    <label className="flex items-center gap-1 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={selectedTags.brand}
                        onChange={() => toggleTag("brand")}
                        className="accent-orange-600"
                      />
                      Brand affiliate
                    </label>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Inline Post Form (existing) */}
          {postingSub === sub.subreddit && (
            <Card className="mt-4 bg-gray-50 border shadow-inner">
              <CardContent className="p-4">
                {/* Conditional post form based on tab/postType */}
                <form onSubmit={handlePostSubmit} className="space-y-3" encType="multipart/form-data">
                  <div className="font-semibold mb-2">Post to r/{postingSub}</div>
                  {/* Text tab */}
                  {postType === "text" && (
                    <>
                      <Input
                        value={postTitle}
                        onChange={(e) => setPostTitle(e.target.value)}
                        maxLength={300}
                        placeholder="Post title"
                        required
                      />
                      <Textarea
                        value={postBody}
                        onChange={(e) => setPostBody(e.target.value)}
                        placeholder="Post body"
                        required={false}
                      />
                    </>
                  )}
                  {/* Media tab */}
                  {postType === "media" && (
                    <>
                      <Input
                        value={postTitle}
                        onChange={(e) => setPostTitle(e.target.value)}
                        maxLength={300}
                        placeholder="Post title"
                        required
                      />
                      {postFiles.length > 0 && (
                        <div>
                          <label className="block font-medium mb-1">Images</label>
                          <div className="mt-2 flex flex-wrap gap-2">
                            {postFiles.map((file, idx) => (
                              <span key={idx} className="text-xs bg-gray-200 px-2 py-1 rounded">
                                {file.name}
                              </span>
                            ))}
                            <button
                              type="button"
                              className="ml-2 text-red-600 text-xs"
                              onClick={handleClearFiles}
                            >
                              Clear
                            </button>
                          </div>
                        </div>
                      )}
                    </>
                  )}
                  {/* Link tab */}
                  {postType === "link" && (
                    <>
                      <Input
                        value={postTitle}
                        onChange={(e) => setPostTitle(e.target.value)}
                        maxLength={300}
                        placeholder="Post title"
                        required
                      />
                      <Input
                        value={link}
                        onChange={() => {}} // controlled by parent
                        placeholder="Link URL"
                        required
                        disabled
                      />
                    </>
                  )}
                  {postError && <div className="text-red-600">{postError}</div>}
                  <div className="flex gap-2 mt-2">
                    <button
                      type="submit"
                      className="bg-blue-700 text-white px-3 py-1.5 rounded hover:bg-blue-800 disabled:opacity-60"
                      disabled={postLoading}
                    >
                      {postLoading ? "Posting..." : "Submit Post"}
                    </button>
                    <button
                      type="button"
                      className="px-3 py-1.5 rounded bg-gray-200 hover:bg-gray-300"
                      onClick={() => {
                        setPostingSub(null);
                        if (fileInputRef.current) fileInputRef.current.value = "";
                      }}
                      disabled={postLoading}
                    >
                      Cancel
                    </button>
                  </div>
                </form>
              </CardContent>
            </Card>
          )}
        </div>
      </CardContent>
    </Card>
  );
};

export default SubredditCard;
