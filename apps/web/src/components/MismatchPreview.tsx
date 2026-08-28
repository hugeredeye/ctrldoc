export function MismatchPreview() {
  return (
    <div className="mismatch-preview" aria-label="Фрагмент рабочей области CTRL DOC">
      <div className="preview-topline">
        <span>REQ-041</span>
        <span>Производительность</span>
        <strong>ВЫСОКИЙ РИСК</strong>
      </div>
      <div className="preview-requirement">
        <span>Требование заказчика</span>
        <p>Система должна поддерживать не менее 10 000 одновременных пользователей.</p>
      </div>
      <div className="preview-mapping">
        <span>Aegis Enterprise</span><i>→</i><span>7.4 LTS</span><i>→</i><span>Масштабирование</span>
      </div>
      <div className="preview-evidence">
        <div className="preview-evidence-head">
          <span>Техническая спецификация.pdf · стр. 39</span>
          <strong>НЕДОСТАТОЧНО ДОКАЗАТЕЛЬСТВ</strong>
        </div>
        <blockquote>
          Система поддерживает до <mark>10 000 зарегистрированных пользователей</mark> в одной
          инсталляции.
        </blockquote>
      </div>
      <div className="preview-verification">
        <div>
          <span>Семантически близко</span>
          <strong>Доказательство найдено</strong>
        </div>
        <i>→</i>
        <div className="preview-guardrail">
          <span>Разные показатели</span>
          <strong>Зарегистрированные ≠ одновременные</strong>
        </div>
        <i>→</i>
        <div>
          <span>Эффективный вердикт</span>
          <strong>Недостаточно доказательств</strong>
        </div>
      </div>
      <div className="preview-decision">
        <span>Безопасный отказ CTRL</span>
        <strong>Недостаточно данных · требуется проверка человеком</strong>
      </div>
    </div>
  );
}
