// Sign-out's part of the offline cache (P27 track F, D-69): every person's copies deleted, here and by the worker
// ({type: "clear"}, its answer awaited for at most a moment: a worker that is busy or gone never holds sign-out).
// Loaded with the account menu's lower part and the command palette, never with a page.

/** The worker that controls this origin now, or null (none registered, or the browser has none). */
export async function activeWorker(): Promise<ServiceWorker | null> {
  try {
    return (await navigator.serviceWorker?.getRegistration("/"))?.active ?? null;
  } catch {
    return null;
  }
}

/** Sends `message` to `worker` and resolves with its answer, or null after `wait` ms. Never rejects. */
export function tellWorker(worker: ServiceWorker | null, message: object, wait = 1500): Promise<unknown> {
  if (!worker) return Promise.resolve(null);
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(null), wait);
    const channel = new MessageChannel();
    channel.port1.onmessage = (event) => {
      clearTimeout(timer);
      resolve(event.data);
    };
    try {
      worker.postMessage(message, [channel.port2]);
    } catch {
      clearTimeout(timer);
      resolve(null);
    }
  });
}

/** The prefix of every person's offline cache (sw.js PEOPLE). */
export const PERSON_CACHE_PREFIX = "trackers-";

/**
 * Sign-out (before the request that ends the session): every person's offline copies are deleted, here and by the
 * worker ({type: "clear"}), and both are awaited. A browser without the Cache API or a worker has nothing to delete.
 */
export async function forgetOffline(): Promise<void> {
  try {
    const store = globalThis.caches;
    if (store) {
      const names = (await store.keys()).filter((name) => name.startsWith(PERSON_CACHE_PREFIX));
      await Promise.all(names.map((name) => store.delete(name)));
    }
  } catch {
    // Blocked storage holds nothing to delete.
  }
  await tellWorker(await activeWorker(), { type: "clear" });
}
