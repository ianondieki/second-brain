"use client";

import { useEffect, useRef, type ReactNode } from "react";

/**
 * Marks its box `data-run` the first time half of it is on screen, once; the figures inside (.count, globals.css)
 * then count up from 0 in CSS. The figures are the server's: without this script, or under reduced motion, they
 * stand as they are, and assistive technology reads the real figure (an sr-only copy) either way.
 */
export function CountUp({ children, className }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const box = ref.current!;
    if (!("IntersectionObserver" in window)) return void (box.dataset.run = "");
    const seen = new IntersectionObserver(
      ([entry]) => {
        if (!entry?.isIntersecting) return;
        box.dataset.run = "";
        seen.disconnect();
      },
      { threshold: 0.5 },
    );
    seen.observe(box);
    return () => seen.disconnect();
  }, []);
  return (
    <div ref={ref} data-count-up="" className={className}>
      {children}
    </div>
  );
}
