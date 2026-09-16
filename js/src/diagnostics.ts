import type { ModelPricing } from "./models.js";

export type DiagnosticSeverity = "info" | "warning" | "error";
export type DiagnosticAction = "skipped_entry" | "ignored_field";

export interface PricingDiagnostic {
  model: string;
  severity: DiagnosticSeverity;
  code: string;
  action: DiagnosticAction;
  path: Array<string | number>;
  message: string;
}

export interface PricingParseResult {
  models: Record<string, ModelPricing>;
  diagnostics: PricingDiagnostic[];
}
