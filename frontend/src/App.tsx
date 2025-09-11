// src/App.tsx
import React, { useState, useEffect } from "react";
import RedditAnalyzer from "./RedditAnalyzer";
import { apiFetch, apiUrl } from "./lib/api";
import { SHOW_DEBUG } from "./lib/config";

interface RedditUser {
  name: string;
  icon_img?: string;
}

function App() {
  const [user, setUser] = useState<RedditUser | null>(null);

  // Fetch user info (checks auth via cookie)
  const fetchUser = async () => {
    try {
      const res = await apiFetch("/api/auth/me");
      if (!res.ok) throw new Error("Not logged in");
      const data = await res.json();
      setUser({ name: data.name, icon_img: data.icon_img });
    } catch {
      setUser(null);
    }
  };

  // Handle OAuth callback that comes to frontend
  const handleOAuthCallback = async (code: string, state: string) => {
    try {
      console.log("Handling OAuth callback on frontend, redirecting to backend...");
      const backendCallbackUrl = apiUrl(
        `/api/auth/reddit/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(
          state
        )}`
      );
      window.location.href = backendCallbackUrl;
    } catch (error) {
      console.error("Failed to handle OAuth callback:", error);
    }
  };

  // On load, check for login via /api/auth/me (cookie-based)
  useEffect(() => {
    // Check if we're returning from OAuth callback
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");

    if (code && state) {
      console.log("OAuth callback detected on frontend");
      handleOAuthCallback(code, state);
      return;
    }

    fetchUser();
  }, []);

  const handleLogin = () => {
    const loginUrl = apiUrl("/api/auth/reddit/login");
    console.log("Redirecting to login URL:", loginUrl);
    try {
      window.location.href = loginUrl;
    } catch (error) {
      console.error("Failed to redirect to login:", error);
      window.open(loginUrl, "_blank");
    }
  };

  const handleDebug = async () => {
    try {
      const res = await apiFetch("/api/auth/debug");
      const data = await res.json();
      console.log("Backend auth configuration:", data);
      alert(`Backend config:\n${JSON.stringify(data, null, 2)}`);
    } catch (error) {
      console.error("Failed to fetch debug info:", error);
      alert("Failed to fetch debug info. Check console for details.");
    }
  };

  const handleLogout = async () => {
    try {
      await apiFetch("/api/auth/logout", { method: "POST" });
    } finally {
      setUser(null);
    }
  };

  return (
    <div>
      {/* Header: single-line layout, no overlap, text truncates if necessary */}
      <header className="flex items-center justify-between gap-3 p-4 border-b mb-4">
        {/* Title takes remaining space; truncate on small screens */}
        <h2 className="flex-1 min-w-0 font-bold truncate text-xl sm:text-2xl">
          Find A Subreddit <br></br>(beta)
        </h2>

        {/* Right controls never wrap and never shrink into the title */}
        <div className="flex items-center gap-2 sm:gap-3 flex-shrink-0 whitespace-nowrap">
          {user ? (
            <div className="flex items-center gap-2 sm:gap-3 flex-shrink-0 whitespace-nowrap">
              <a
                href={`https://www.reddit.com/user/${user.name}/`}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 hover:underline min-w-0"
                title="Go to Reddit profile"
              >
                {user.icon_img && (
                  <img
                    src={user.icon_img}
                    alt={user.name}
                    className="w-7 h-7 sm:w-8 sm:h-8 rounded-full border flex-shrink-0"
                    referrerPolicy="no-referrer"
                  />
                )}
                {/* Username truncates to avoid pushing the button */}
                <span className="font-semibold max-w-[40vw] sm:max-w-none truncate">
                  {user.name}
                </span>
              </a>
              <button
                onClick={handleLogout}
                className="bg-gray-200 rounded px-3 py-1.5 sm:px-3 sm:py-1.5 text-sm sm:text-base hover:bg-gray-300 flex-shrink-0 whitespace-nowrap"
              >
                Log out
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2 sm:gap-3 flex-shrink-0 whitespace-nowrap">
              <button
                onClick={handleLogin}
                className="bg-orange-500 rounded px-3 py-1.5 sm:px-4 sm:py-2 text-sm sm:text-base text-white font-bold hover:bg-orange-600 flex-shrink-0 whitespace-nowrap"
              >
                Log in with Reddit
              </button>
              {SHOW_DEBUG && (
                <button
                  onClick={handleDebug}
                  className="bg-gray-500 rounded px-3 py-1.5 text-sm text-white hover:bg-gray-600 flex-shrink-0 whitespace-nowrap"
                  title="Debug backend configuration"
                >
                  Debug
                </button>
              )}
            </div>
          )}
        </div>
      </header>

      <RedditAnalyzer user={user} onLoginClick={handleLogin} />
    </div>
  );
}

export default App;
