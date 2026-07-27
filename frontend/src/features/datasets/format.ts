/**
 * Human-readable rendering of file metadata.
 */

const UNITS = ["B", "KB", "MB", "GB"] as const;
const STEP = 1024;

/**
 * Render a byte count the way a person would say it.
 *
 * Divides by 1024, not 1000, while keeping the familiar "MB" labels. The
 * backend's limit is expressed in binary units (`200 * 1024 * 1024` in
 * `backend/app/core/config.py`), so a decimal divisor here would render that
 * exact limit as "209.7 MB" and the message would contradict the rule it is
 * explaining.
 *
 * One decimal place below 10 and none above, because "1.5 KB" is useful and
 * "209.7 MB" is noise.
 */
export function formatFileSize(bytes: number): string {
  let value = bytes;
  let unit = 0;

  while (value >= STEP && unit < UNITS.length - 1) {
    value /= STEP;
    unit += 1;
  }

  const rounded = unit === 0 ? String(value) : value.toFixed(value < 10 ? 1 : 0);
  return `${rounded} ${UNITS[unit]}`;
}
