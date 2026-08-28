import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

function requirementPanel() {
  return screen.getByRole("region", { name: "Требования" });
}

describe("CTRL Intelligence Workbench", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("selects a requirement and opens its grounded detail", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(
      within(requirementPanel()).getByRole("button", {
        name: /развёртывание active-active между регионами/i,
      }),
    );

    expect(
      screen.getByRole("heading", {
        name: /Платформа должна поддерживать развёртывание active-active между регионами/i,
      }),
    ).toBeVisible();
    expect(screen.getByText("Только в плане развития")).toBeVisible();
    expect(screen.getByText("Aegis 8.0 (план)")).toBeVisible();
  });

  it("filters the list by proposed decision", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Частично" }));

    const panel = requirementPanel();
    expect(within(panel).getByText("REQ-118")).toBeVisible();
    expect(within(panel).queryByText("REQ-041")).not.toBeInTheDocument();
    expect(within(panel).getByText("1 показано")).toBeVisible();
  });

  it("shows only risk-routed requirements in Needs Review", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Требует проверки" }));

    const panel = requirementPanel();
    expect(within(panel).queryByText("REQ-024")).not.toBeInTheDocument();
    expect(within(panel).getByText("REQ-041")).toBeVisible();
    expect(within(panel).getByText("6 показано")).toBeVisible();
  });

  it("makes the semantic-neighbour mismatch and safe abstention explicit", () => {
    render(<App />);

    expect(screen.getAllByText("Зарегистрированные ≠ одновременные").length).toBeGreaterThan(0);
    expect(screen.getByText("Показатели не совпадают")).toBeVisible();
    expect(screen.getByText("Несовпадение показателей")).toBeVisible();
    expect(screen.getByText("CTRL не делает неподтверждённое обещание")).toBeVisible();
    expect(screen.getByText("Недостаточно данных · UNKNOWN · требуется проверка человеком")).toBeVisible();
    expect(screen.getByText("10 000 зарегистрированных пользователей")).toBeVisible();
  });

  it("never hides either side of an authoritative conflict", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(
      within(requirementPanel()).getByRole("button", {
        name: /Резервное копирование должно выполняться без остановки сервисов/i,
      }),
    );

    expect(screen.getByRole("heading", { name: "Источники противоречат друг другу" })).toBeVisible();
    expect(screen.getAllByText("Подтверждает").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Противоречит").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Операционный бюллетень 03/).length).toBeGreaterThan(0);
    expect(screen.getByText(/не выбирает удобный источник автоматически/i)).toBeVisible();
  });

  it("records human approval in local demo state only", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Подтвердить" }));

    expect(screen.getByText("Подтверждено человеком в демо")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("только в состоянии демо");
    expect(screen.getByRole("button", { name: "Подтверждено" })).toBeDisabled();
  });

  it("does not make external API or model calls", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByRole("searchbox", { name: "Поиск требований" }), "REQ-041");
    await user.click(screen.getByRole("button", { name: "Требует проверки" }));

    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("provides an obvious return path to the landing", () => {
    render(<App />);

    expect(screen.getByRole("link", { name: "← На главную" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "CTRL DOC — на главную" })).toHaveAttribute("href", "/");
  });
});
