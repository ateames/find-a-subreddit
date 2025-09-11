import React, { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../lib/api";
import AddSubredditModal from "./AddSubreddit";
import SubredditCard from "./SubredditCard";

type RedditUser = { name: string; icon_img?: string } | null;

type SubItem = {
  name: string; // plain name, e.g. "javascript"
  display_name_prefixed?: string; // e.g. "r/javascript"
  title?: string;
  icon_img?: string | null;
  community_icon?: string | null;
  subscribers?: number | null;
};

interface Props {
  user: RedditUser;
  onLoginClick: () => void;
  /** Override if your API isn’t on localhost */
  apiBase?: string; // default: http://localhost:8001
  className?: string;
}

const CACHE_KEY = "subs_menu_cache_v1";
const MAX_AGE_MS = 10 * 60 * 1000; // 10 min

function pickIcon(s: SubItem): string | null {
  // community_icon sometimes has a querystring; also sometimes empty string
  const com = (s.community_icon || "").split("?")[0];
  if (com) return com;
  if (s.icon_img) return s.icon_img;
  return null;
}

function formatCount(n?: number | null) {
  if (!n && n !== 0) return "";
  if (n < 1000) return `${n}`;
  const units = ["", "k", "M", "B"];
  const idx = Math.floor(Math.log10(n) / 3);
  const v = n / Math.pow(1000, idx);
  return `${v.toFixed(v < 10 ? 1 : 0)}${units[idx]}`;
}

const LeftMenu: React.FC<Props> = ({
  user,
  onLoginClick,
  className = "",
}) => {
  const [subs, setSubs] = useState<SubItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");
  const [query, setQuery] = useState("");

  // load from cache first (fast paint)
  useEffect(() => {
    const raw = sessionStorage.getItem(CACHE_KEY);
    if (raw) {
      try {
        const { ts, data } = JSON.parse(raw);
        if (Date.now() - ts < MAX_AGE_MS && Array.isArray(data)) {
          setSubs(data);
        }
      } catch {}
    }
  }, []);

  // fetch from API when logged in
  useEffect(() => {
    if (!user) return;
    let cancel = false;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const res = await apiFetch(`/api/reddit/subscriptions?limit=1000`);
        if (!res.ok) {
          if (res.status === 401) {
            setError("Not authorized. Please sign in.");
          } else {
            setError(`Failed to load subscriptions (${res.status}).`);
          }
          return;
        }
        const json = await res.json();
        // Be flexible about backend shape: accept {subreddits:[...]} or just [...]
        const list: any[] = Array.isArray(json) ? json : json.subreddits || [];
        const mapped: SubItem[] = list.map((s: any) => ({
          name: s.name || s.display_name || "",
          display_name_prefixed: s.display_name_prefixed || (s.name ? `r/${s.name}` : undefined),
          title: s.title || s.public_description || "",
          icon_img: s.icon_img || null,
          community_icon: s.community_icon || null,
          subscribers: s.subscribers ?? null,
        })).filter((s) => s.name);

        if (!cancel) {
          // sort alpha by name
          mapped.sort((a, b) => a.name.localeCompare(b.name));
          setSubs(mapped);
          sessionStorage.setItem(CACHE_KEY, JSON.stringify({ ts: Date.now(), data: mapped }));
        }
      } catch (e: any) {
        if (!cancel) setError(e?.message || "Network error.");
      } finally {
        if (!cancel) setLoading(false);
      }
    })();
    return () => {
      cancel = true;
    };
  }, [user]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return subs;
    return subs.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        (s.title || "").toLowerCase().includes(q)
    );
  }, [subs, query]);

  return (
    <aside
      className={`h-[calc(100vh-2rem)] sticky top-4 overflow-hidden ${className}`}
      aria-label="Your subreddits"
    >
      <div className="bg-white border rounded-2xl shadow-sm h-full flex flex-col">
        <div className="p-3 border-b">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-base font-semibold">MY COMMUNITIES</h2>
          </div>
          <div className="mt-3">
            <input
              type="text"
              placeholder="Filter communities…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 ring-blue-500"
            />
          </div>
        </div>

        {!user ? (
          <div className="p-4 text-sm">
            <p className="mb-3">Sign in to see your subscriptions.</p>
            <button
              onClick={onLoginClick}
              className="px-3 py-2 rounded-lg bg-orange-500 text-white text-sm hover:opacity-90"
              type="button"
            >
              Sign in with Reddit
            </button>
          </div>
        ) : (
          <>
            {error && (
              <div className="p-3 text-sm text-red-600 border-b">{error}</div>
            )}
            <div className="flex-1 overflow-y-auto">
              {loading && subs.length === 0 ? (
                <ul className="p-3 space-y-2 animate-pulse">
                  {Array.from({ length: 10 }).map((_, i) => (
                    <li key={i} className="flex items-center gap-3">
                      <div className="h-8 w-8 rounded-full bg-gray-200" />
                      <div className="h-4 w-2/3 rounded bg-gray-200" />
                    </li>
                  ))}
                </ul>
              ) : (
                <ul className="p-2">
                  {filtered.map((s) => {
                    const icon = pickIcon(s);
                    const href = `https://www.reddit.com/r/${s.name}/`;
                    return (
                      <li key={s.name}>
                        <a
                          href={href}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center gap-3 px-2 py-2 rounded-lg hover:bg-gray-50 focus:outline-none focus:ring-2 ring-blue-500"
                        >
                          {icon ? (
                            <img
                              src={icon}
                              alt=""
                              className="h-8 w-8 rounded-full object-cover border"
                              onError={(e) => {
                                (e.currentTarget as HTMLImageElement).style.display = "none";
                              }}
                            />
                          ) : (
                            <div className="h-8 w-8 rounded-full bg-gray-200 grid place-items-center text-xs font-medium">
                              r/
                            </div>
                          )}
                          <div className="min-w-0">
                            <div className="text-sm font-medium truncate">
                              {s.display_name_prefixed || `r/${s.name}`}
                            </div>
                            <div className="text-xs text-gray-500 truncate">
                              {s.title || ""} {s.subscribers ? `• ${formatCount(s.subscribers)} subs` : ""}
                            </div>
                          </div>
                        </a>
                      </li>
                    );
                  })}
                  {filtered.length === 0 && !loading && (
                    <li className="p-3 text-sm text-gray-500">No matches.</li>
                  )}
                </ul>
              )}
            </div>
          </>
        )}
      </div>
    </aside>
  );
};

export default LeftMenu;
