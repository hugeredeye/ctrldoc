export function MismatchPreview() {
  return (
    <div className="mismatch-preview" aria-label="Фрагмент Intelligence Workbench">
      <div className="preview-topline">
        <span>REQ-041</span>
        <span>Производительность</span>
        <strong>HIGH RISK</strong>
      </div>
      <div className="preview-requirement">
        <span>Customer requirement</span>
        <p>Система должна поддерживать не менее 10 000 одновременных пользователей.</p>
      </div>
      <div className="preview-mapping">
        <span>Aegis Enterprise</span><i>→</i><span>7.4 LTS</span><i>→</i><span>User scaling</span>
      </div>
      <div className="preview-evidence">
        <div className="preview-evidence-head">
          <span>Техническая спецификация.pdf · стр. 39</span>
          <strong>INSUFFICIENT</strong>
        </div>
        <blockquote>
          Система поддерживает до <mark>10 000 зарегистрированных пользователей</mark> в одной
          инсталляции.
        </blockquote>
      </div>
      <div className="preview-verification">
        <div>
          <span>Семантически близко</span>
          <strong>Evidence found</strong>
        </div>
        <i>→</i>
        <div className="preview-guardrail">
          <span>Разные показатели</span>
          <strong>registered ≠ concurrent</strong>
        </div>
        <i>→</i>
        <div>
          <span>Эффективный вердикт</span>
          <strong>INSUFFICIENT</strong>
        </div>
      </div>
      <div className="preview-decision">
        <span>CTRL safe abstention</span>
        <strong>UNKNOWN · Human review required</strong>
      </div>
    </div>
  );
}
