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
  constructor(message: string) {
    super(message);
    this.name = "PricingSchemaError";
  }
}
