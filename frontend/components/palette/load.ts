// The command palette's code is a chunk of its own, fetched the first time someone opens it (Ctrl/⌘ K, "/" or the
// Search button), or a moment earlier when the pointer rests on the button or it takes focus: no route's first load
// carries it (docs/spec/07 item 5, the 150 KB budget per route). One request, however often it is asked for.
let palette: Promise<typeof import("./CommandPalette")> | null = null;

export function loadPalette() {
  palette ??= import("./CommandPalette").catch((error: unknown) => {
    palette = null; // offline: the next press tries again
    throw error;
  });
  return palette;
}
