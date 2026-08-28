import { lazy, Suspense } from "react";

import { LandingPage } from "./LandingPage";

const Workbench = lazy(async () => {
  const module = await import("./App");
  return { default: module.App };
});

const GuidedDemo = lazy(async () => {
  const module = await import("./GuidedDemo");
  return { default: module.GuidedDemo };
});

export function Site({ path = window.location.pathname }: { path?: string }) {
  if (path === "/demo/guided" || path.startsWith("/demo/guided/")) {
    return (
      <Suspense fallback={<div role="status">Загрузка проверки…</div>}>
        <GuidedDemo />
      </Suspense>
    );
  }

  if (path === "/demo" || path.startsWith("/demo/")) {
    return (
      <Suspense fallback={<div role="status">Загрузка рабочей области…</div>}>
        <Workbench />
      </Suspense>
    );
  }
  return <LandingPage />;
}
