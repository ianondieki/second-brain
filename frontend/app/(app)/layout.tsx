import { PageTransition } from "@/components/motion/PageTransition";

/** The signed-in portals' pages: a route change between them cross-fades where View Transitions run (D-67, P25). */
export default function PortalLayout({ children }: LayoutProps<"/">) {
  return <PageTransition>{children}</PageTransition>;
}
