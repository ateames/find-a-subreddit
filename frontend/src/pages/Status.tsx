// src/pages/Status.tsx
import React, { useEffect, useState } from "react";
import { API_URL } from "../lib/config";
import { apiFetch } from "../lib/api";

export default function Status() {
  const [startup, setStartup] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const s = await apiFetch("/startup-status");
        const h = await apiFetch("/health");
        setStartup(await s.json());
        setHealth(await h.json());
      } catch (e: any) {
        setErr(e?.message || String(e));
      }
    })();
  }, []);

  return (
    <div style={{ padding: 16 }}>
      <h1>Status</h1>
      <p><strong>VITE_API_URL</strong>: {API_URL}</p>
      {err && <p style={{ color: "red" }}>Error: {err}</p>}
      <h2>Backend /startup-status</h2>
      <pre>{startup ? JSON.stringify(startup, null, 2) : "Loading..."}</pre>
      <h2>Backend /health</h2>
      <pre>{health ? JSON.stringify(health, null, 2) : "Loading..."}</pre>
    </div>
  );
}
