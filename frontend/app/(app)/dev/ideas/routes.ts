import type { Step } from "./ideas";

// Reading the editor's URL on the server (kept out of the editor's bundle).

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export function isProposalId(value: string): boolean {
  return UUID.test(value);
}

export function parseStep(value: string | string[] | undefined): Step {
  const raw = Array.isArray(value) ? value[0] : value;
  return raw === "2" ? 2 : raw === "3" ? 3 : 1;
}
