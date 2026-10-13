// Cargo load weight, in lb; the route endpoint accepts the same range.
export const WEIGHT_MIN = 1_000;
export const WEIGHT_MAX = 100_000;
export const WEIGHT_STEP = 1_000;
export const WEIGHT_DEFAULT = 20_000;

export const pounds = (lb) => `${lb.toLocaleString()} lb`;

