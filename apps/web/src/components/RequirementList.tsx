import type { KeyboardEvent } from "react";

import type { AtomicRequirement, ComplianceStatus, ReviewUpdate } from "../types";
import { Icon } from "./Icon";
import { StatusPill } from "./StatusPill";

export type DecisionFilter = "ALL" | ComplianceStatus;

interface RequirementListProps {
  allCount: number;
  decisionFilter: DecisionFilter;
  needsReviewOnly: boolean;
  onDecisionFilterChange: (filter: DecisionFilter) => void;
  onNeedsReviewChange: (enabled: boolean) => void;
  onQueryChange: (query: string) => void;
  onSelect: (id: string) => void;
  query: string;
  requirements: AtomicRequirement[];
  reviewUpdates: Record<string, ReviewUpdate>;
  selectedId: string;
}

const filterOptions: { label: string; value: DecisionFilter }[] = [
  { label: "Все", value: "ALL" },
  { label: "Соответствует", value: "COMPLY" },
  { label: "Частично", value: "PARTIAL" },
  { label: "Нет данных", value: "UNKNOWN" },
  { label: "Уточнить", value: "NEEDS_CLARIFICATION" },
];

export function RequirementList({
  allCount,
  decisionFilter,
  needsReviewOnly,
  onDecisionFilterChange,
  onNeedsReviewChange,
  onQueryChange,
  onSelect,
  query,
  requirements,
  reviewUpdates,
  selectedId,
}: RequirementListProps) {
  const moveSelection = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const nextIndex = event.key === "ArrowDown" ? index + 1 : index - 1;
    const next = requirements[Math.max(0, Math.min(requirements.length - 1, nextIndex))];
    if (!next) return;
    onSelect(next.id);
    document.getElementById(`requirement-${next.id}`)?.focus();
  };

  return (
    <section className="requirements-panel" aria-labelledby="requirements-heading">
      <div className="panel-heading requirements-heading">
        <div>
          <p className="eyebrow">Атомарные требования</p>
          <h1 id="requirements-heading">Требования</h1>
        </div>
        <span className="count-label">{allCount} в демо</span>
      </div>

      <div className="requirement-tools">
        <label className="search-box">
          <Icon name="search" size={17} />
          <span className="sr-only">Поиск требований</span>
          <input
            aria-label="Поиск требований"
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="ID или текст требования"
            type="search"
            value={query}
          />
          <kbd>Ctrl K</kbd>
        </label>

        <div className="filter-row" aria-label="Фильтры решений">
          <div className="filter-scroll">
            {filterOptions.map((option) => (
              <button
                aria-pressed={decisionFilter === option.value}
                className="filter-chip"
                key={option.value}
                onClick={() => onDecisionFilterChange(option.value)}
                type="button"
              >
                {option.label}
              </button>
            ))}
          </div>
          <button
            aria-pressed={needsReviewOnly}
            className="review-filter"
            onClick={() => onNeedsReviewChange(!needsReviewOnly)}
            type="button"
          >
            <Icon name="filter" size={15} />
            Требует проверки
          </button>
        </div>
      </div>

      <div className="list-caption" aria-hidden="true">
        <span>Требование</span>
        <span>Решение / риск</span>
      </div>

      <div className="requirement-list" role="list" aria-live="polite">
        {requirements.length === 0 ? (
          <div className="empty-state">
            <Icon name="search" size={22} />
            <strong>Ничего не найдено</strong>
            <span>Сбросьте фильтры или измените запрос.</span>
          </div>
        ) : (
          requirements.map((requirement, index) => {
            const update = reviewUpdates[requirement.id];
            const decision = update?.decision ?? requirement.decision;
            return (
              <div className="requirement-row-wrap" key={requirement.id} role="listitem">
                <button
                  aria-current={selectedId === requirement.id}
                  className="requirement-row"
                  id={`requirement-${requirement.id}`}
                  onClick={() => onSelect(requirement.id)}
                  onKeyDown={(event) => moveSelection(event, index)}
                  type="button"
                >
                  <span className="row-accent" />
                  <span className="requirement-copy">
                    <span className="requirement-meta">
                      <span className="requirement-id">{requirement.shortId}</span>
                      <span>{requirement.category}</span>
                    </span>
                    <span className="requirement-text">{requirement.text}</span>
                    {requirement.needsReview && (
                      <span className="attention-note">
                        <Icon name="flag" size={13} /> Требует внимания
                      </span>
                    )}
                  </span>
                  <span className="row-statuses">
                    <StatusPill value={decision} />
                    <StatusPill value={requirement.risk} quiet />
                  </span>
                </button>
              </div>
            );
          })
        )}
      </div>
      <div className="list-footer">
        <span>{requirements.length} показано</span>
        <span>↑↓ навигация</span>
      </div>
    </section>
  );
}
