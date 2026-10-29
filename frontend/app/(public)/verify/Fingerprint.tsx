import { cn } from "@/components/ui/cn";

import { fingerprintGroups } from "./certificate";

/**
 * A SHA-256 fingerprint as eight groups of eight hex digits: two groups a line on a phone, four from 640 px, so two
 * fingerprints line up when compared by eye. Hex letters have no tabular form in the text face, so this one element
 * uses the system monospace stack (still no web font). The groups are inline boxes, not separate words:
 * selecting and copying the fingerprint gives the 64 digits with no spaces.
 */
export function Fingerprint({ hex, className }: { hex: string; className?: string }) {
  return (
    <p
      data-fingerprint={hex}
      className={cn(
        "max-w-[18ch] font-mono text-lg leading-8 text-ink [overflow-wrap:anywhere] sm:max-w-[36ch]",
        className,
      )}
    >
      {fingerprintGroups(hex).map((group, index) => (
        <span key={index} className="inline-block w-[9ch]">
          {group}
        </span>
      ))}
    </p>
  );
}
