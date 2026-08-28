import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import landingStyles from "./landing.css?raw";
import { LandingPage } from "./LandingPage";
import { Site } from "./Site";

describe("CTRL DOC public landing", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("presents the Russian positioning and complete core message", () => {
    render(<LandingPage />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Точно знайте, что можно обещать заказчику.",
      }),
    ).toBeVisible();
    expect(
      screen.getByText(/CTRL проверяет требования по документации продукта, версиям и первоисточникам/),
    ).toBeVisible();
    expect(screen.getByText("RFP / RFI / ТЗ")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Похоже — не значит доказано." })).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Сначала — требования. Потом — доказательства." }),
    ).toBeVisible();
    expect(screen.getByRole("heading", { name: "ИИ находит. CTRL проверяет." })).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Каждое обязательство. Под CTRL." }),
    ).toBeVisible();
  });

  it("connects every desktop navigation item to its matching section", () => {
    const { container } = render(<LandingPage />);
    const navigation = screen.getByRole("navigation", { name: "Основная навигация" });
    const expectedTargets = {
      Продукт: "#product",
      "Как работает": "#how-it-works",
      Технология: "#technology",
      Безопасность: "#security",
      Компания: "#company",
    };

    for (const [name, target] of Object.entries(expectedTargets)) {
      const link = within(navigation).getByRole("link", { name });
      expect(link).toHaveAttribute("href", target);
      expect(container.querySelector(target)).not.toBeNull();
    }

    const security = container.querySelector("#security");
    expect(security).toHaveAccessibleName("Корпоративные документы не должны становиться платой за автоматизацию.");
    expect(within(security as HTMLElement).getByText("10 / Безопасность")).toBeVisible();
  });

  it("routes marketing calls to action through the guided demo first", () => {
    render(<LandingPage />);

    expect(screen.getByRole("link", { name: "Проверить на примере" })).toHaveAttribute(
      "href",
      "/demo/guided",
    );
    expect(screen.getByRole("link", { name: "Бесплатное демо" })).toHaveAttribute(
      "href",
      "/demo/guided",
    );
    expect(screen.getByRole("link", { name: "Сначала пройти безопасное демо →" })).toHaveAttribute(
      "href",
      "/demo/guided",
    );
  });

  it("keeps the guided experience available at /demo/guided", async () => {
    render(<Site path="/demo/guided" />);

    expect(
      await screen.findByRole("heading", { name: "ИИ находит. CTRL проверяет." }),
    ).toBeVisible();
    expect(screen.getByText("Реальные документы не принимаются и никуда не загружаются.")).toBeVisible();
  });

  it("keeps the existing Intelligence Workbench available at /demo", async () => {
    render(<Site path="/demo" />);

    expect(
      await screen.findByRole("main", { name: "Рабочая область CTRL DOC" }),
    ).toBeVisible();
    expect(screen.getByText("RFP-2026-014 · Корпоративная платформа")).toBeVisible();
  });

  it("supports keyboard press and release on the CTRL keycap", () => {
    render(<LandingPage />);
    const keycap = screen.getAllByRole("button", { name: "Перейти к проверке CTRL" })[0];

    fireEvent.keyDown(keycap, { key: " " });
    expect(keycap).toHaveAttribute("data-pressed", "true");

    fireEvent.keyUp(keycap, { key: " " });
    expect(keycap).toHaveAttribute("data-pressed", "false");
  });

  it("opens, switches, and closes the accessible product-model accordion", async () => {
    const user = userEvent.setup();
    render(<LandingPage />);
    const capability = screen.getByRole("button", { name: /01 Возможность/ });
    const evidence = screen.getByRole("button", { name: /03 Доказательство/ });

    expect(evidence).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Руководство администратора 7.4")).toBeVisible();
    expect(capability).toHaveAttribute("aria-expanded", "false");

    await user.click(capability);
    expect(capability).toHaveAttribute("aria-expanded", "true");
    expect(evidence).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("Масштабирование пользователей")).toBeVisible();
    expect(screen.queryByText("Руководство администратора 7.4")).not.toBeInTheDocument();

    await user.click(capability);
    expect(capability).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Масштабирование пользователей")).not.toBeInTheDocument();
  });

  it("operates the product-model accordion from the keyboard", async () => {
    const user = userEvent.setup();
    render(<LandingPage />);
    const version = screen.getByRole("button", { name: /02 Версия/ });

    version.focus();
    await user.keyboard("{Enter}");

    expect(version).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("CTRL не переносит доказательство между версиями автоматически.")).toBeVisible();
    expect(screen.getByRole("button", { name: /03 Доказательство/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("provides a reduced-motion CSS policy for all landing interactions", () => {
    render(<LandingPage />);

    expect(landingStyles).toContain("@media (prefers-reduced-motion: reduce)");
    expect(landingStyles).toMatch(/animation-duration:\s*0\.01ms/);
    expect(
      screen.getAllByRole("button", { name: "Перейти к проверке CTRL" })[0],
    ).toHaveAttribute("data-motion", "css-reduced-motion-aware");
  });

  it("does not make external API or inference calls", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<LandingPage />);

    await user.type(screen.getByRole("textbox", { name: "Имя" }), "Анна");
    await user.type(screen.getByRole("textbox", { name: "Рабочий email" }), "anna@example.com");
    await user.type(screen.getByRole("textbox", { name: "Компания" }), "Example");
    await user.selectOptions(screen.getByRole("combobox", { name: "Что хотите проверить?" }), "RFP");
    await user.click(screen.getByRole("button", { name: /Подготовить запрос на пилот/ }));

    expect(screen.getByRole("status")).toHaveTextContent("автоматическая отправка пока не подключена");
    expect(
      (screen.getByRole("textbox", { name: "Проверьте текст заявки" }) as HTMLTextAreaElement)
        .value,
    ).toContain("Рабочий email: anna@example.com");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("does not publish pricing, careers, fake metrics, providers, or certification claims", () => {
    render(<LandingPage />);

    expect(screen.queryByText(/₽\s*\/|тариф|pricing/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/карьер|ваканси|we.?re hiring/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\+87%|10x|100\+ compan/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/DeepSeek|OpenAI/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/SOC\s*2|ISO\s*27001|ФСТЭК|ФСБ|152-ФЗ/i)).not.toBeInTheDocument();
  });
});
