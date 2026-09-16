import { Decimal as DecimalJs } from "decimal.js";

export const Decimal = DecimalJs.clone({
  precision: 50,
  rounding: DecimalJs.ROUND_HALF_UP
});

export type Decimal = InstanceType<typeof Decimal>;
