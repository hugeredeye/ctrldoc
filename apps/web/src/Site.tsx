import { lazy, Suspense } from "react";

import { LandingPage } from "./LandingPage";

const Workbench = lazy(async () => {
  const module = await import("./App");
  return { default: module.App };
});

export function Site({ path = window.location.pathname }: { path?: string }) {
  if (path === "/demo" || path.startsWith("/demo/")) {
    return (
      <Suspense fallback={<div role="status">Загрузка Workbench…</div>}>
        <Workbench />
      </Suspense>
    );
  }
  return <LandingPage />;
}
