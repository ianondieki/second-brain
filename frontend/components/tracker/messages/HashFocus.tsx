"use client";

import { useEffect } from "react";

/**
 * The Messages route lands where its address points (REQ-ENG-11): "#messages-heading" (the tab bar, the N18 links) or
 * "#message-<id>" (the History tab). Focus goes there, also after an in-app navigation (which otherwise leaves focus
 * on the page's h1); a message older than the first page is not on it, so focus goes to the thread's heading.
 */
export function HashFocus({ fallback }: { fallback: string }) {
  useEffect(() => {
    const hash = decodeURIComponent(location.hash.slice(1));
    if (hash) (document.getElementById(hash) ?? document.getElementById(fallback))?.focus();
  }, [fallback]);
  return null;
}
