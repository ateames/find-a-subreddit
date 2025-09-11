// src/components/AddSubredditModal.tsx
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import AddSubreddit, { Subreddit } from "./AddSubreddit";

interface AddSubredditModalProps {
  triggerLabel?: string;
  triggerClassName?: string;
  closeOnResolved?: boolean;
  renderCard?: (sub: Subreddit) => React.ReactNode;
  onResolved?: (sub: Subreddit, existed: boolean) => void;
  defaultValue?: string;
  endpoints?: {
    check: (normalizedName: string) => string;
    add: string;
  };
}

export default function AddSubredditModal({
  triggerLabel = "Add a Subreddit",
  triggerClassName,
  closeOnResolved = true,
  renderCard,
  onResolved,
  defaultValue,
  endpoints,
}: AddSubredditModalProps) {
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  // Focus subreddit input when the modal opens
  useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => {
      const el = document.getElementById("subreddit-input") as HTMLInputElement | null;
      el?.focus();
      el?.select();
    }, 50);
    return () => clearTimeout(t);
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  // Prevent body scroll when open
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  const handleResolved = useCallback(
    (sub: Subreddit, existed: boolean) => {
      onResolved?.(sub, existed);
      if (closeOnResolved) setOpen(false);
    },
    [onResolved, closeOnResolved]
  );

  const triggerClasses = useMemo(
    () =>
      triggerClassName ??
      "inline-flex items-center gap-2 rounded-xl bg-black px-4 py-2 text-white hover:opacity-90 dark:bg-white dark:text-black",
    [triggerClassName]
  );

  const modalNode = open ? (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="add-subreddit-title"
      onMouseDown={(e) => {
        // Close on outside click
        if (e.target === e.currentTarget) setOpen(false);
      }}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-[1px]" />

      {/* Panel */}
      <div className="relative z-[1001] mx-3 w-full max-w-2xl origin-center rounded-2xl border bg-white p-4 shadow-xl dark:border-neutral-800 dark:bg-neutral-900 animate-in fade-in zoom-in-95">
        <div className="flex items-start justify-between gap-4">
          <h2 id="add-subreddit-title" className="text-lg font-semibold">
            Add a Subreddit
          </h2>
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="rounded-lg border px-2 py-1 text-sm hover:bg-gray-50 dark:border-neutral-700 dark:hover:bg-neutral-800"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="mt-3">
          <AddSubreddit
            renderCard={renderCard}
            onResolved={handleResolved}
            defaultValue={defaultValue}
            endpoints={endpoints}
          />
        </div>
      </div>
    </div>
  ) : null;

  return (
    <>
      <button
        type="button"
        className={triggerClasses}
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls="add-subreddit-modal"
      >
        {triggerLabel}
      </button>

      {mounted && modalNode ? createPortal(modalNode, document.body) : null}
    </>
  );
}
