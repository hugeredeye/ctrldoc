import type { ComplianceStatus, RiskLevel, VerifierVerdict } from "../types";

export type PillValue = ComplianceStatus | RiskLevel | VerifierVerdict | "APPROVED" | "PENDING";

export const statusLabels: Record<PillValue, string> = {
  APPROVED: "Подтверждено",
  BLOCKING: "Блокирующий риск",
  COMPLY: "Соответствует",
  CONTRADICTS: "Противоречит",
  ENTAILS: "Подтверждает",
  GAP: "Не покрыто",
  HIGH: "Высокий риск",
  INSUFFICIENT: "Недостаточно доказательств",
  LOW: "Низкий риск",
  MEDIUM: "Средний риск",
  NEEDS_CLARIFICATION: "Требует уточнения",
  PARTIAL: "Частично соответствует",
  PENDING: "Ожидает проверки",
  UNKNOWN: "Недостаточно данных",
};
