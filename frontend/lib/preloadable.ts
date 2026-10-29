// Code split for the browser, whole on the server (docs/spec/07 item 5). React.lazy suspends once even when its module
// is already loaded, so the server streams a lazily loaded part after the rest of the page and the browser paints the
// page without it first: a layout shift. A preloadable module is a promise React's `use` can read synchronously once
// fulfilled: on the server it is loaded when the module is (before any request renders), in the browser only when a
// component first reads it.

type Tracked<T> = Promise<T> & { status?: "pending" | "fulfilled" | "rejected"; value?: T; reason?: unknown };

export function preloadable<T>(load: () => Promise<T>): () => Promise<T> {
  let promise: Tracked<T> | null = null;
  const get = () => {
    if (!promise) {
      const tracked = load() as Tracked<T>;
      tracked.status = "pending";
      tracked.then(
        (value) => {
          tracked.status = "fulfilled";
          tracked.value = value;
        },
        (reason: unknown) => {
          tracked.status = "rejected";
          tracked.reason = reason;
        },
      );
      promise = tracked;
    }
    return promise;
  };
  if (typeof window === "undefined") void get();
  return get;
}
