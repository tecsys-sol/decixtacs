"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

import { GOTO_SHORTCUTS } from "@/lib/nav";

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

/** Global keyboard shortcuts: Cmd/Ctrl+K, "g <key>" navigation, "?" help. */
export function useGlobalShortcuts({ onSearch, onHelp }: { onSearch: () => void; onHelp: () => void }) {
  const router = useRouter();
  const pendingG = useRef<number | null>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onSearch();
        return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return;
      if (document.querySelector("[role=dialog]")) return;

      if (pendingG.current !== null) {
        window.clearTimeout(pendingG.current);
        pendingG.current = null;
        const href = GOTO_SHORTCUTS[e.key.toLowerCase()];
        if (href) {
          e.preventDefault();
          router.push(href);
        }
        return;
      }
      if (e.key === "g") {
        pendingG.current = window.setTimeout(() => {
          pendingG.current = null;
        }, 1200);
        return;
      }
      if (e.key === "?") {
        e.preventDefault();
        onHelp();
      } else if (e.key === "/") {
        e.preventDefault();
        onSearch();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      if (pendingG.current !== null) window.clearTimeout(pendingG.current);
    };
  }, [router, onSearch, onHelp]);
}
