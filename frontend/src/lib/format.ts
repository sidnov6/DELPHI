const CCY_SYMBOL: Record<string, string> = {
  USD: "$", EUR: "€", GBP: "£", CHF: "CHF ", JPY: "¥",
  SEK: "kr ", NOK: "kr ", DKK: "kr ", CAD: "C$", AUD: "A$", HKD: "HK$",
};

/** Currency code → display symbol; unknown codes render as "CODE ". */
export const ccy = (code?: string | null) =>
  CCY_SYMBOL[code ?? "USD"] ?? `${code} `;

export const fmtPrice = (v: number, currency = "$") =>
  `${currency}${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export const fmtPct = (v: number, signed = true) =>
  `${signed && v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;

export const fmtB = (v: number, sym = "$") =>
  v >= 1000 ? `${sym}${(v / 1000).toFixed(2)}T` : `${sym}${v.toFixed(1)}B`;

export const fmtX = (v: number) => `${v.toFixed(1)}×`;

export const stanceTone = (s: number): "pos" | "neg" | "neutral" =>
  s > 0.35 ? "pos" : s < -0.35 ? "neg" : "neutral";

export const fmtStance = (s: number) => `${s > 0 ? "+" : ""}${s.toFixed(1)}`;
