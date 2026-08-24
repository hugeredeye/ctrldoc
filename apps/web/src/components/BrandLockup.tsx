interface BrandLockupProps {
  compact?: boolean;
  inverse?: boolean;
}

export function BrandLockup({ compact = false, inverse = false }: BrandLockupProps) {
  return (
    <div className={`landing-brand${compact ? " landing-brand-compact" : ""}${inverse ? " landing-brand-inverse" : ""}`}>
      <span className="landing-brand-key" aria-hidden="true">CTRL</span>
      <span className="landing-brand-copy">
        <strong>CTRL DOC</strong>
        {!compact && <span>Response Intelligence</span>}
      </span>
    </div>
  );
}
