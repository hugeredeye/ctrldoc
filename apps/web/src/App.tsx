import { useEffect, useMemo, useRef, useState } from "react";

import "./landing.css";
import "./styles.css";

import { BrandLockup } from "./components/BrandLockup";
import { DetailPanel } from "./components/DetailPanel";
import { Icon } from "./components/Icon";
import {
  type DecisionFilter,
  RequirementList,
} from "./components/RequirementList";
import { demoRequirements } from "./data/demoCases";
import type { ComplianceStatus, ReviewState, ReviewUpdate } from "./types";

const workflow = ["Документ", "Требования", "Доказательства", "Проверка", "Ответ"];

export function App() {
  const [selectedId, setSelectedId] = useState("req-041");
  const [query, setQuery] = useState("");
  const [decisionFilter, setDecisionFilter] = useState<DecisionFilter>("ALL");
  const [needsReviewOnly, setNeedsReviewOnly] = useState(false);
  const [reviewUpdates, setReviewUpdates] = useState<Record<string, ReviewUpdate>>({});
  const searchRef = useRef<HTMLInputElement | null>(null);

  const requirementsWithUpdates = useMemo(
    () =>
      demoRequirements.map((requirement) => {
        const update = reviewUpdates[requirement.id];
        return update ? { ...requirement, decision: update.decision, reviewState: update.state } : requirement;
      }),
    [reviewUpdates],
  );

  const filteredRequirements = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase("ru");
    return requirementsWithUpdates.filter((requirement) => {
      const matchesQuery =
        normalizedQuery.length === 0 ||
        requirement.text.toLocaleLowerCase("ru").includes(normalizedQuery) ||
        requirement.shortId.toLocaleLowerCase("ru").includes(normalizedQuery);
      const matchesDecision =
        decisionFilter === "ALL" || requirement.decision === decisionFilter;
      const matchesReview = !needsReviewOnly || requirement.needsReview;
      return matchesQuery && matchesDecision && matchesReview;
    });
  }, [decisionFilter, needsReviewOnly, query, requirementsWithUpdates]);

  const selected =
    requirementsWithUpdates.find((requirement) => requirement.id === selectedId) ??
    filteredRequirements[0] ??
    requirementsWithUpdates[0];

  useEffect(() => {
    const focusSearch = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", focusSearch);
    return () => window.removeEventListener("keydown", focusSearch);
  }, []);

  const updateDecision = (decision: ComplianceStatus) => {
    setReviewUpdates((current) => ({
      ...current,
      [selected.id]: {
        decision,
        state: current[selected.id]?.state ?? selected.reviewState,
      },
    }));
  };

  const updateReviewState = (state: ReviewState) => {
    setReviewUpdates((current) => ({
      ...current,
      [selected.id]: {
        decision: current[selected.id]?.decision ?? selected.decision,
        state,
      },
    }));
  };

  const counts = requirementsWithUpdates.reduce<Record<ComplianceStatus, number>>(
    (accumulator, requirement) => {
      accumulator[requirement.decision] += 1;
      return accumulator;
    },
    { COMPLY: 0, PARTIAL: 0, GAP: 0, UNKNOWN: 0, NEEDS_CLARIFICATION: 0 },
  );

  return (
    <div className="app-shell">
      <header className="app-header">
        <a aria-label="CTRL DOC — на главную" className="app-brand-link" href="/">
          <BrandLockup compact inverse />
        </a>

        <div className="project-context">
          <span>Демо-проект</span>
          <div aria-label="Текущий демо-проект" className="project-name">
            RFP-2026-014 · Корпоративная платформа
            <Icon name="chevron-down" size={14} />
          </div>
        </div>

        <div className="header-actions">
          <a className="workbench-home-link" href="/">← На главную</a>
          <div className="demo-badge" title="Только детерминированные синтетические данные">
            <span /> <strong>ДЕМО</strong><em>· СИНТЕТИЧЕСКИЕ ДАННЫЕ</em>
          </div>
        </div>
      </header>

      <nav className="workflow-bar" aria-label="Этапы проверки">
        <div className="workflow-steps">
          {workflow.map((step, index) => {
            const complete = index < 3;
            const active = step === "Проверка";
            return (
              <div
                aria-current={active ? "step" : undefined}
                className={`workflow-step${complete ? " is-complete" : ""}${active ? " is-active" : ""}`}
                key={step}
              >
                <span>{complete ? <Icon name="check" size={12} /> : index + 1}</span>
                <strong>{step}</strong>
                {index < workflow.length - 1 && <i />}
              </div>
            );
          })}
        </div>
        <div className="workflow-summary" aria-label="Сводка решений">
          <span><strong>{demoRequirements.length}</strong> требований</span>
          <span className="summary-comply"><strong>{counts.COMPLY}</strong> соответствуют</span>
          <span className="summary-partial"><strong>{counts.PARTIAL}</strong> частично</span>
          <span className="summary-unknown"><strong>{counts.UNKNOWN}</strong> недостаточно данных</span>
          <span className="summary-clarify"><strong>{counts.NEEDS_CLARIFICATION}</strong> уточнить</span>
        </div>
      </nav>

      <main className="workbench" aria-label="Рабочая область CTRL DOC">
        <div ref={(node) => { searchRef.current = node?.querySelector("input") ?? null; }} className="requirements-wrap">
          <RequirementList
            allCount={demoRequirements.length}
            decisionFilter={decisionFilter}
            needsReviewOnly={needsReviewOnly}
            onDecisionFilterChange={setDecisionFilter}
            onNeedsReviewChange={setNeedsReviewOnly}
            onQueryChange={setQuery}
            onSelect={setSelectedId}
            query={query}
            requirements={filteredRequirements}
            reviewUpdates={reviewUpdates}
            selectedId={selected.id}
          />
        </div>
        <DetailPanel
          decision={selected.decision}
          key={selected.id}
          onDecisionChange={updateDecision}
          onReviewStateChange={updateReviewState}
          requirement={selected}
          reviewState={selected.reviewState}
        />
      </main>
    </div>
  );
}
