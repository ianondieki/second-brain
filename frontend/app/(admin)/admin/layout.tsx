import { PageTransition } from "@/components/motion/PageTransition";

import { staffContext } from "./staff";

/** Every /admin page is staff only: the gate runs here before any page of the console renders. A change of section
 *  cross-fades where View Transitions run (D-67, P25). */
export default async function StaffConsoleLayout({ children }: LayoutProps<"/admin">) {
  await staffContext();
  return <PageTransition>{children}</PageTransition>;
}
