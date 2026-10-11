// WattTime reports CO₂ rates in lb/MWh and the server sums CO₂ in lb.
// The dashboard shows g/kWh and kg.
const KG_PER_LB = 0.45359237;

export const RATE = "g/kWh";
/** Convert lb/MWh to g/kWh. */
export const rate = (lbMwh: number) => lbMwh * KG_PER_LB;
export const fmtRate = (lbMwh: number) => `${Math.round(rate(lbMwh))} ${RATE}`;
/** Convert lb to kg. */
export const kg = (lb: number) => lb * KG_PER_LB;
