"use client";

import { useEffect, useState } from "react";

/** Subtle cue when FRIDAY runs inside `apps/desktop` (Electron preload). */
export function DesktopShellBadge() {
  const [shown, setShown] = useState(false);

  useEffect(() => {
    setShown(typeof window !== "undefined" && Boolean(window.fridayDesktop));
  }, []);

  if (!shown) return null;

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[100] rounded border border-emerald-500/30 bg-zinc-950/90 px-2 py-1 text-[10px] uppercase tracking-[0.2em] text-emerald-400/90">
      Desktop shell
    </div>
  );
}
