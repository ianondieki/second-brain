// Attachment helpers for the Full details step (loaded on demand) and the idea page (server-rendered).

// The attachment types the API accepts (bridge/proposals/editor.py ACCEPTED_TYPES), by file extension: browsers
// give Markdown files no type or several different ones, so the extension decides what is sent.
const TYPE_BY_EXTENSION: Record<string, string> = {
  pdf: "application/pdf",
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  md: "text/markdown",
  markdown: "text/markdown",
  txt: "text/plain",
};

export const ACCEPT_ATTRIBUTE = ".pdf,.png,.jpg,.jpeg,.md,.markdown,.txt";

export function attachmentType(name: string): string | null {
  const dot = name.lastIndexOf(".");
  return dot < 0 ? null : (TYPE_BY_EXTENSION[name.slice(dot + 1).toLowerCase()] ?? null);
}

/** File sizes as people read them: "820 KB", "4.2 MB" (1 KB = 1,000 bytes, as the size limit is stated). */
export function fileSizeParts(bytes: number): { value: number; unit: "bytes" | "kb" | "mb" } {
  if (bytes < 1000) return { value: bytes, unit: "bytes" };
  if (bytes < 1_000_000) return { value: Math.round(bytes / 1000), unit: "kb" };
  return { value: Math.round(bytes / 100_000) / 10, unit: "mb" };
}
