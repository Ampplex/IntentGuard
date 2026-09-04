// Money arrives as integer paise and is only ever turned into rupees for
// display. Nothing here converts in the other direction, because nothing in the
// browser is allowed to decide an amount.
export function rupees(paise) {
  if (paise === null || paise === undefined) return "—";
  const sign = paise < 0 ? "-" : "";
  const whole = Math.floor(Math.abs(paise) / 100);
  const part = String(Math.abs(paise) % 100).padStart(2, "0");
  return `${sign}₹${whole.toLocaleString("en-IN")}.${part}`;
}
