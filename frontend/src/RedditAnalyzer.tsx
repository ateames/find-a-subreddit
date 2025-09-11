// This file is getting a little messy I should consider refactoring components but I'm lazy and it works.

import React, { useState, useRef, useEffect, useCallback } from "react";
import PostForm from "./components/PostForm";
import ImageCaptions from "./components/ImageCaptions";
import SubredditResultsList from "./components/SubredditResultsList";
import LoginModal from "./components/LoginModal";
import RedditMagnifyLoader from "./components/ui/RedditMagnifyLoader";
import LeftMenu from "./components/LeftMenu";
import { apiFetch } from "./lib/api";
import { SHOW_TEST_SUB } from "./lib/config";
import HeaderBanner from "./components/HeaderBanner";

interface SubredditResult {
  subreddit: string;
  score?: number;
  description?: string;
  rules?: string[];
  ai_warning?: string[];
  subscribers?: number;
}

interface RedditUser {
  name: string;
  icon_img?: string;
}

interface RedditAnalyzerProps {
  user: RedditUser | null;
  onLoginClick: () => void;
}

type PostType = "text" | "media" | "link";
type MainTab = "find" | "post";

function abbreviateNumber(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs < 1_000) return `${value}`;
  if (abs < 10_000) {
    const thousands = Math.floor(abs / 100) / 10;
    return `${sign}${thousands.toFixed(1)}k`;
  }
  if (abs < 1_000_000) {
    const thousands = Math.floor(abs / 1_000);
    return `${sign}${thousands}k`;
  }
  if (abs < 10_000_000) {
    const millions = Math.floor(abs / 100_000) / 10;
    return `${sign}${millions.toFixed(1)}M`;
  }
  const millions = Math.floor(abs / 1_000_000);
  return `${sign}${millions}M`;
}

const CONTEXT_EXAMPLE =
  "e.g. 'A supportive community for new parents' or 'A place to share and discuss sci-fi art'";

const TEST_SUB: SubredditResult = {
  subreddit: "test",
  score: 1,
  description:
    "A subreddit for testing purposes only. This subreddit is used to test the Reddit API and bot functionality.",
  rules: [
    "No spam outside of test purposes.",
    "UNo onlyfans promos, and nsfw posts.",
  ],
  ai_warning: [],
  subscribers: 32000,
};

const RedditAnalyzer: React.FC<RedditAnalyzerProps> = ({ user, onLoginClick }) => {
  // --- Main (new) Tabs ---
  const [activeTab, setActiveTab] = useState<MainTab>("find");

  // --- Post Type Tabs (only used in "post" mode) ---
  const [postType, setPostType] = useState<PostType>("text");

  // --- Input State ---
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [context, setContext] = useState("");
  const [link, setLink] = useState("");
  const [contextFocused, setContextFocused] = useState(false);

  const [results, setResults] = useState<SubredditResult[]>([]);
  const [imageCaptions, setImageCaptions] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);

  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const observerRef = useRef<IntersectionObserver | null>(null);

  // For posting UI
  const [postFiles, setPostFiles] = useState<File[]>([]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [postingSub, setPostingSub] = useState<string | null>(null);
  const [postTitle, setPostTitle] = useState("");
  const [postBody, setPostBody] = useState("");
  const [postError, setPostError] = useState("");
  const [postLoading, setPostLoading] = useState(false);
  const [postConfirmations, setPostConfirmations] = useState<{ [sub: string]: string }>({});

  // Login modal state
  const [loginModalOpen, setLoginModalOpen] = useState(false);
  const [pendingPostSub, setPendingPostSub] = useState<string | null>(null);

  // --- Switch between "Find" and "Post" tabs ---
  const handleSwitchMainTab = (tab: MainTab) => {
    setActiveTab(tab);
    setError("");
    // Keep context if moving between tabs; clear post-only fields when switching to "find" for clarity
    if (tab === "find") {
      setTitle("");
      setBody("");
      setLink("");
      setPostFiles([]);
      setPostType("text");
    }
    // Keep results visible across tabs so user can still act on them
  };

  // --- Infinite scroll handler ---
  const loadMoreResults = useCallback(async () => {
    if (loading || !hasMore) return;
    setLoading(true);
    setError("");
    try {
      const formData = new FormData();
      // In "find" mode we only use context; other fields are empty
      formData.append("title", activeTab === "post" ? title : "");
      formData.append("body", activeTab === "post" ? body : "");
      formData.append("context", context.trim());
      formData.append("page", (page + 1).toString());
      if (activeTab === "post" && postType === "media" && postFiles.length) {
        postFiles.forEach((file) => formData.append("files", file));
      }
      if (activeTab === "post" && postType === "link") {
        formData.append("link", link);
      }
      const res = await apiFetch("/api/analyze_post", {
        method: "POST",
        body: formData,
      });
      if (!res.ok) throw new Error("API error");
      const data = await res.json();
      setResults((prev) => [...prev, ...(((data.results as SubredditResult[]) || []))]);
      setImageCaptions(data.image_captions || []);
      setPage((prev) => prev + 1);
      setHasMore(data.has_more);
    } catch {
      setError("Failed to load more results. Please try again.");
    } finally {
      setLoading(false);
    }
  }, [activeTab, title, body, context, postFiles, page, hasMore, loading, postType, link]);

  useEffect(() => {
    if (!sentinelRef.current) return;
    if (observerRef.current) observerRef.current.disconnect();
    observerRef.current = new window.IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !loading) {
          loadMoreResults();
        }
      },
      { threshold: 1.0 }
    );
    observerRef.current.observe(sentinelRef.current);
    return () => {
      if (observerRef.current) observerRef.current.disconnect();
    };
  }, [results, hasMore, loading, loadMoreResults]);

  const handleAnalyze = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setResults([]);
    setImageCaptions([]);
    setPostingSub(null);
    setPage(1);
    setHasMore(false);

    const titleTrimmed = title.trim();
    const bodyTrimmed = body.trim();
    const contextTrimmed = context.trim();
    const linkTrimmed = link.trim();

    // --- Validation for the new "Find a Subreddit" tab (context-only) ---
    if (activeTab === "find") {
      if (!contextTrimmed) {
        setError("Please describe what you're looking for in the Context box.");
        return;
      }
    } else {
      // --- Validation for "Post to a Subreddit" flow (existing logic) ---
      if (postType === "text") {
        if (!titleTrimmed && !bodyTrimmed && !contextTrimmed) {
          setError("Please enter a post title, body, or context.");
          return;
        }
        if (!titleTrimmed && !!bodyTrimmed && !contextTrimmed) {
          setError("Please enter a post title or context. Post body alone is not enough.");
          return;
        }
      }
      if (postType === "media" && !titleTrimmed && postFiles.length === 0 && !contextTrimmed) {
        setError("Please add a title, select an image, or enter context.");
        return;
      }
      if (postType === "link") {
        if (!titleTrimmed && !linkTrimmed && !contextTrimmed) {
          setError("Please enter a post title, link, or context.");
          return;
        }
        if (!linkTrimmed && !titleTrimmed) {
          setError("Please enter a link or title for your post.");
          return;
        }
      }
    }

    setLoading(true);

    try {
      const formData = new FormData();
      formData.append("title", activeTab === "post" ? title : "");
      formData.append("body", activeTab === "post" ? body : "");
      formData.append("context", contextTrimmed);
      formData.append("page", "1");

      if (activeTab === "post" && postType === "media" && postFiles.length) {
        postFiles.forEach((file) => formData.append("files", file));
      }
      if (activeTab === "post" && postType === "link") {
        formData.append("link", linkTrimmed);
      }

      const res = await apiFetch("/api/analyze_post", {
        method: "POST",
        body: formData,
      });
      if (!res.ok) throw new Error("API error");
      const data = await res.json();
      setResults((data.results as SubredditResult[]) || []);
      setImageCaptions(data.image_captions || []);
      setPage(1);
      setHasMore(data.has_more);
    } catch {
      setError("Failed to analyze post. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  // --- Posting to Reddit logic  ---
  const handleSubmitToReddit = async (e: React.FormEvent) => {
    e.preventDefault();
    setPostLoading(true);
    setPostError("");

    // --- Custom validation for Media tab ---
    if (postType === "media" && (!postFiles || postFiles.length === 0)) {
      setPostError("Oops! You need to select at least one image to post. 📸");
      setPostLoading(false);
      return;
    }

    // --- Custom validation for Link tab ---
    if (postType === "link" && (!link || link.trim() === "")) {
      setPostError("Uh-oh! You need to enter a valid URL before you can post a link. 🔗");
      setPostLoading(false);
      return;
    }

    try {
      if (!user) {
        setPostError("You must be logged in to post to Reddit.");
        setPostLoading(false);
        return;
      }
      const flair_id = (window as any).__selectedFlair || "";
      const tags = (window as any).__selectedTags || {};
      const nsfw = tags.nsfw ? "true" : "false";
      const brand_affiliate = tags.brand ? "true" : "false";

      const formData = new FormData();
      formData.append("subreddit", postingSub!);
      formData.append("title", postTitle);

      if (postType === "text") {
        formData.append("body", postBody);
      } else if (postType === "media" && postFiles.length) {
        postFiles.forEach((file) => formData.append("files", file));
      } else if (postType === "link") {
        formData.append("link", link);
      }
      if (flair_id) formData.append("flair_id", flair_id);
      formData.append("nsfw", nsfw);
      formData.append("brand_affiliate", brand_affiliate);

      const res = await apiFetch("/api/reddit/post_to_reddit", {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.error || "Failed to post to Reddit.");
      }
      setPostConfirmations((prev) => ({ ...prev, [postingSub!]: data.url }));
      setPostTitle("");
      setPostBody("");
      setPostingSub(null);
      setPostFiles([]);
      if (fileInputRef.current) fileInputRef.current.value = "";
      (window as any).__selectedFlair = "";
      (window as any).__selectedTags = {};
    } catch (err: any) {
      setPostError(err.message || "Failed to post to Reddit.");
    } finally {
      setPostLoading(false);
    }
  };

  const handleContextFocus = () => setContextFocused(true);
  const handleContextBlur = () => setContextFocused(false);

  const handleClearFiles = () => {
    setPostFiles([]);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleRequestPostToSubreddit = (subreddit: string) => {
    if (!user) {
      setPendingPostSub(subreddit);
      setLoginModalOpen(true);
      return;
    }
    setPostingSub(subreddit);
  };

  // --- Searching state & list composition ---
  const isSearching = loading && results.length === 0 && !error;
  const resultsWithoutTest = results.filter((r) => r.subreddit !== "test");

  // Inject r/test only when allowed by SHOW_TEST_SUB
  const resultsWithTestSub: SubredditResult[] = isSearching
    ? (resultsWithoutTest as SubredditResult[])
    : (SHOW_TEST_SUB ? ([TEST_SUB, ...resultsWithoutTest] as SubredditResult[]) : (resultsWithoutTest as SubredditResult[]));

  // --- Layout with left menu + main content ---
  return (
    <div className="max-w-7xl mx-auto py-10 px-4 grid grid-cols-12 gap-6">
      <aside className="hidden md:block col-span-3">
        {/* Use the login prop you already have; do NOT call undefined fetchUser */}
        <LeftMenu user={user} onLoginClick={onLoginClick} />
      </aside>

      <main className="col-span-12 md:col-span-9">
        <div className="max-w-2xl mx-auto">
          {/* Hero / Header */}
          <HeaderBanner
            className="mb-6"
            onStartClick={() =>
              document.getElementById("post-form")?.scrollIntoView({ behavior: "smooth" })
            }
          />

          {/* === New Top-Level Tabs === */}
          <div className="mb-6 flex justify-center">
            <nav className="flex rounded-xl bg-muted p-1 shadow-inner w-full max-w-xl" aria-label="Primary">
              <button
                type="button"
                className={`flex-1 py-2 rounded-lg text-base font-medium transition ${
                  activeTab === "find" ? "bg-white shadow text-black" : "hover:bg-gray-100 text-gray-500"
                }`}
                onClick={() => handleSwitchMainTab("find")}
              >
                Find a Subreddit
              </button>
              <button
                type="button"
                className={`flex-1 py-2 rounded-lg text-base font-medium transition ${
                  activeTab === "post" ? "bg-white shadow text-black" : "hover:bg-gray-100 text-gray-500"
                }`}
                onClick={() => handleSwitchMainTab("post")}
              >
                Post to a Subreddit
              </button>
            </nav>
          </div>

          {/* === FIND MODE: Context-only search form === */}
          {activeTab === "find" && (
            <section id="post-form" className="mb-8">
              <form onSubmit={handleAnalyze} className="space-y-4">
                <div>
                  <label htmlFor="context" className="block text-md font-medium mb-1">
                  What community are you trying to find? We’ll match subreddits.
                  </label>
                  <textarea
                    id="context"
                    name="context"
                    value={context}
                    onChange={(e) => setContext(e.target.value)}
                    onFocus={handleContextFocus}
                    onBlur={handleContextBlur}
                    placeholder={CONTEXT_EXAMPLE}
                    rows={4}
                    className={`w-full rounded-xl border border-gray-200 dark:border-neutral-700
                                bg-white dark:bg-neutral-900 p-3 outline-none
                                text-gray-900 dark:text-gray-100
                                placeholder-gray-500 dark:placeholder-gray-400
                                focus:ring-2 focus:ring-blue-500 ${
                                  contextFocused ? "ring-2 ring-blue-500" : ""
                                }`}
                  />
                  <p className="mt-2 text-xs text-gray-500">
                    Describe the community you’re looking for. We’ll suggest matches.
                  </p>
                </div>

                {error && (
                  <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                    {error}
                  </div>
                )}

                <div className="flex justify-end">
                  <button
                    type="submit"
                    className="w-full rounded-xl bg-indigo-600 px-5 py-3 font-semibold text-white shadow-md transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-70"
                    disabled={loading}
                    aria-busy={loading}
                  >
                    {loading ? "Finding Subreddits…" : "Find a Subreddit"}
                  </button>
                </div>
              </form>
            </section>
          )}

          {/* === POST MODE: existing flow with Text / Images / Link === */}
          {activeTab === "post" && (
            <>
              <h2 className="text-xl font-semibold mb-3">1. Select post type</h2>
              <div id="post-form" className="mb-6 flex justify-center">
                <nav className="flex rounded-xl bg-muted p-1 shadow-inner w-full max-w-lg" aria-label="Post type">
                  <button
                    className={`flex-1 py-2 rounded-lg text-base font-medium transition ${
                      postType === "text" ? "bg-white shadow text-black" : "hover:bg-gray-100 text-gray-500"
                    }`}
                    onClick={() => setPostType("text")}
                    type="button"
                  >
                    Text
                  </button>
                  <button
                    className={`flex-1 py-2 rounded-lg text-base font-medium transition ${
                      postType === "media" ? "bg-white shadow text-black" : "hover:bg-gray-100 text-gray-500"
                    }`}
                    onClick={() => setPostType("media")}
                    type="button"
                  >
                    Images
                  </button>
                  <button
                    className={`flex-1 py-2 rounded-lg text-base font-medium transition ${
                      postType === "link" ? "bg-white shadow text-black" : "hover:bg-gray-100 text-gray-500"
                    }`}
                    onClick={() => setPostType("link")}
                    type="button"
                  >
                    Link
                  </button>
                </nav>
              </div>

              <PostForm
                postType={postType}
                title={title}
                setTitle={setTitle}
                body={body}
                setBody={setBody}
                context={context}
                setContext={setContext}
                contextFocused={contextFocused}
                setContextFocused={setContextFocused}
                onContextFocus={handleContextFocus}
                onContextBlur={handleContextBlur}
                link={link}
                setLink={setLink}
                postFiles={postFiles}
                setPostFiles={setPostFiles}
                fileInputRef={fileInputRef}
                handleClearFiles={handleClearFiles}
                loading={loading}
                onSubmit={handleAnalyze}
                error={error}
                contextExample={CONTEXT_EXAMPLE}
              />
            </>
          )}

          <ImageCaptions imageCaptions={imageCaptions} />

          {/* Inline loader appears where the first card would be, only during initial search */}
          {isSearching && (
            <div className="rounded-xl border bg-white dark:bg-neutral-900 p-8 flex items-center justify-center min-h-[180px] mb-4 text-gray-700 dark:text-gray-100">
              <RedditMagnifyLoader size={200} durationMs={4200} ariaLabel="Finding matching subreddits…" />
            </div>
          )}

          <SubredditResultsList
            resultsWithTestSub={resultsWithTestSub}
            abbreviateNumber={abbreviateNumber}
            title={title}
            body={body}
            link={link}
            postType={postType}
            postingSub={postingSub}
            setPostingSub={setPostingSub}
            postTitle={postTitle}
            setPostTitle={setPostTitle}
            postBody={postBody}
            setPostBody={setPostBody}
            postError={postError}
            setPostError={setPostError}
            postLoading={postLoading}
            handleSubmitToReddit={handleSubmitToReddit}
            postConfirmations={postConfirmations}
            postFiles={postFiles}
            handleClearFiles={handleClearFiles}
            fileInputRef={fileInputRef}
            sentinelRef={sentinelRef}
            loading={loading}
            hasMore={hasMore}
            onRequestPostToSubreddit={handleRequestPostToSubreddit}
            user={user}
          />

          <LoginModal
            open={loginModalOpen}
            onClose={() => setLoginModalOpen(false)}
            onLoginClick={onLoginClick}
          />
        </div>
      </main>
    </div>
  );
};

export default RedditAnalyzer;
