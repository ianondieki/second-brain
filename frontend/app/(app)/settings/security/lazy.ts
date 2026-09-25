import { lazy } from "react";

// Parts of /settings/security that appear only after an action or an error load on demand, keeping the route under
// the 150 KiB gzipped JS budget (docs/spec/07 item 5). React.lazy, not next/dynamic: it adds no runtime, and none of
// these parts render on the server.

export const loadEnrolmentSteps = () => import("./EnrolmentSteps");

/** Steps 1-3 after "Turn on": QR encoder, key, code confirmation, recovery codes. */
export const EnrolmentSteps = lazy(() => loadEnrolmentSteps().then((m) => ({ default: m.EnrolmentSteps })));

/** The fresh-code form that turning two-step sign-in off may ask for. */
export const StepUpForm = lazy(() => import("./StepUpForm").then((m) => ({ default: m.StepUpForm })));

/** "Email me a sign-in link" for recent_sign_in_required. */
export const SignInAgain = lazy(() => import("./SignInAgain").then((m) => ({ default: m.SignInAgain })));
