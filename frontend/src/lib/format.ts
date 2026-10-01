/** Formatting helpers. Kept in one place so units and precision stay consistent. */

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function formatDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

export function formatShortDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
}

export function pct(value: number, digits = 0): string {
  return `${value.toFixed(digits)}%`;
}

/** Sensible precision per variable: rainfall in whole mm, pressure to 1 dp. */
export function formatValue(value: number, unit: string): string {
  const digits = unit === 'hPa' ? 1 : unit === 'degC' ? 1 : unit === 'm/s' ? 1 : 0;
  return `${value.toFixed(digits)} ${displayUnit(unit)}`;
}

export function displayUnit(unit: string): string {
  return unit === 'degC' ? '°C' : unit;
}

export function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}
