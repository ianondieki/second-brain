import { cloneElement, isValidElement, type ReactElement, type ReactNode } from "react";

const AsyncFunction = (async () => undefined).constructor;

/**
 * Resolves a server component tree for a jsdom test: every async function component reachable through `children`
 * is awaited and replaced by what it returned, so the result renders with testing-library (React's client renderer
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
  if (element.props && "children" in element.props) {
    return cloneElement(element, { children: await resolveServerTree(element.props.children) });
  }
  return element;
}
