import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import guidedStyles from "./guided.css?raw";
import { GuidedDemo } from "./GuidedDemo";

describe("CTRL guided synthetic-safe demo", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("walks through evidence, guardrail, and human approval", async () => {
    const user = userEvent.setup();
    render(<GuidedDemo />);

    expect(screen.getByText(/аутентификацию через/)).toBeVisible();
    expect(screen.getByRole("heading", { name: "Соответствует" })).toBeVisible();
    expect(screen.getByText("COMPLY · доказательство применимо")).toBeVisible();

    await user.click(screen.getByRole("button", { name: /Показать защитную проверку/ }));
    expect(screen.getByText(/10 000 одновременных пользователей/)).toBeVisible();
    expect(screen.getByText(/Система поддерживает до/)).toBeVisible();
    expect(screen.getAllByText("Зарегистрированные ≠ одновременные").length).toBeGreaterThan(0);
    expect(screen.getByText("Недостаточно доказательств")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Недостаточно данных" })).toBeVisible();

    await user.click(screen.getByRole("button", { name: /Показать роль человека/ }));
    expect(screen.getByRole("heading", { name: "Требуется финальное подтверждение" })).toBeVisible();

    await user.click(screen.getByRole("button", { name: /Подтвердить безопасный ответ/ }));

    expect(screen.getByRole("status")).toHaveTextContent("Подтверждено человеком в демо");
    expect(screen.getByRole("link", { name: /Открыть рабочую область/ })).toHaveAttribute(
      "href",
      "/demo",
    );
  });

  it("does not call external APIs and supports reduced motion", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<GuidedDemo />);

    await user.click(screen.getByRole("button", { name: /Показать защитную проверку/ }));

    expect(screen.getByRole("heading", { name: "Недостаточно данных" })).toBeVisible();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(guidedStyles).toContain("@media (prefers-reduced-motion: reduce)");
  });

  it("offers a visible route back to the landing", () => {
    render(<GuidedDemo />);

    expect(screen.getByRole("link", { name: "← На главную" })).toHaveAttribute("href", "/");
  });
});
