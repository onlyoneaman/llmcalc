import type { PricingDiagnostic } from "./diagnostics.js";

export class PricingError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PricingError";
  }
}

export class PricingFetchError extends PricingError {
  constructor(message: string) {
    super(message);
    this.name = "PricingFetchError";
  }
}

export class PricingSchemaError extends PricingError {
  readonly diagnostics: PricingDiagnostic[];

  constructor(message: string, diagnostics: PricingDiagnostic[] = []) {
    super(message);
    this.name = "PricingSchemaError";
    this.diagnostics = diagnostics;
  }
}

export class PricingHistoryError extends PricingError {
  constructor(message: string) {
    super(message);
    this.name = "PricingHistoryError";
  }
}
