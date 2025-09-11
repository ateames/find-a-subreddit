import React from "react";

interface HeaderBannerProps {
  /** Optional handler for the primary CTA */
  onStartClick?: () => void;
  /** Optional extra classes for outer wrapper */
  className?: string;
}

/**
 * Simple, visually rich hero/header banner.
 * - Keeps copy concise
 * - Subtle gradients + blurred orbs for depth
 * - Accessible, responsive, production‑ready
 */
export default function HeaderBanner({ onStartClick, className }: HeaderBannerProps) {
  const handleStart = () => {
    if (onStartClick) return onStartClick();
    const el = document.getElementById("post-form");
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <header
      className={[
        "relative isolate overflow-hidden",
        "rounded-3xl",
        "bg-gradient-to-br from-indigo-600 via-violet-600 to-fuchsia-600",
        "shadow-2xl ring-1 ring-white/10",
        className || "",
      ].join(" ")}
      aria-label="Find the best subreddit for your post"
    >
      {/* Decorative background accents */}
      <div className="pointer-events-none absolute -top-24 -left-20 h-72 w-72 rounded-full bg-white/20 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-28 -right-28 h-80 w-80 rounded-full bg-fuchsia-400/30 blur-3xl" />
      <div
        aria-hidden
        className="absolute inset-0 -z-10 opacity-50"
        style={{
          backgroundImage:
            "radial-gradient(1000px_1000px_at_10%_10%, rgba(255,255,255,.10), transparent 40%), radial-gradient(800px_800px_at_90%_90%, rgba(255,255,255,.08), transparent 40%)",
        }}
      />

      <div className="mx-auto max-w-7xl px-6 py-8 sm:py-10 lg:py-10">
        <div className="mx-auto max-w-3xl text-center">
          <h1 className="text-balance text-4xl font-semibold tracking-tight text-white sm:text-5xl">
            Find the best subreddit for your post.
          </h1>
          <p className="mt-4 text-pretty text-lg text-white/90">
            We scan thousands of communities, flag rules & vibe, and suggest quick fixes to avoid removals.
          </p>
        </div>
      </div>
    </header>
  );
}