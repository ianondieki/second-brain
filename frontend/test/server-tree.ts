import { cloneElement, isValidElement, type ReactElement, type ReactNode } from "react";

const AsyncFunction = (async () => undefined).constructor;

/**
 * Resolves a server component tree for a jsdom test: every async function component reachable through `children`
 * (or through any other prop that holds elements, such as PageHero's `aside` or a card's `band`) is awaited and replaced by what it returned, so the result renders with testing-library (React's client renderer
 * does not run async components). Client components are left as they are and render normally.
 */
export async function resolveServerTree(node: ReactNode): Promise<ReactNode> {
  if (Array.isArray(node)) return Promise.all(node.map((child) => resolveServerTree(child)));
  if (!isValidElement(node)) return node;
  const element = node as ReactElement<{ children?: ReactNode }>;
  if (typeof element.type === "function" && element.type instanceof AsyncFunction) {
    const render = element.type as (props: unknown) => Promise<ReactNode>;
    return resolveServerTree(await render(element.props));
  }
  if (!element.props) return element;
  // children, and any other prop that holds elements (a hero's aside, a card's photograph band, a tile's figure)
  const resolved: Record<string, ReactNode> = {};
  for (const [key, value] of Object.entries(element.props as Record<string, unknown>)) {
    if (key === "children" || isValidElement(value) || (Array.isArray(value) && value.some(isValidElement))) {
      resolved[key] = await resolveServerTree(value as ReactNode);
    }
  }
  return Object.keys(resolved).length > 0 ? cloneElement(element, resolved) : element;
}
