import { staffContext } from "./staff";

/** Every /admin page is staff only: the gate runs here before any page of the console renders. */
export default async function StaffConsoleLayout({ children }: LayoutProps<"/admin">) {
  await staffContext();
  return children;
}
