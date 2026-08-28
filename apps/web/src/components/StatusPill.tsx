import { statusLabels, type PillValue } from "./statusLabels";

export function StatusPill({
  value,
  quiet = false,
  showCode = false,
}: {
  value: PillValue;
  quiet?: boolean;
  showCode?: boolean;
}) {
  return (
    <span
      className={`status-pill status-${value.toLowerCase()}${quiet ? " status-quiet" : ""}`}
      title={`${statusLabels[value]} · ${value}`}
    >
      <span className="status-dot" />
      {statusLabels[value]}
      {showCode && <code>{value}</code>}
    </span>
  );
}
