/**
 * Timestamp utility functions for converting UTC timestamps to local timezone
 */

const ISO_DATE_TIME_WITHOUT_TIMEZONE_RE =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/;

const parseUtcTimestamp = (timestamp: string | Date): Date => {
  if (timestamp instanceof Date) {
    return timestamp;
  }

  const trimmedTimestamp = timestamp.trim();
  const normalizedTimestamp = ISO_DATE_TIME_WITHOUT_TIMEZONE_RE.test(
    trimmedTimestamp,
  )
    ? `${trimmedTimestamp}Z`
    : trimmedTimestamp;
  return new Date(normalizedTimestamp);
};

/**
 * Format a UTC timestamp to local timezone string
 * @param timestamp - UTC timestamp from backend (ISO format string or Date object)
 * @returns Formatted local time string
 */
export const formatTimestamp = (timestamp: string | Date | undefined): string => {
  if (!timestamp) return '';

  const date = parseUtcTimestamp(timestamp);

  if (isNaN(date.getTime())) return '';

  return date.toLocaleString('en-US', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  }).replace(',', '');
};

/**
 * Format a UTC timestamp to local timezone string with date only
 * @param timestamp - UTC timestamp from backend
 * @returns Formatted local date string
 */
export const formatDate = (timestamp: string | Date | undefined): string => {
  if (!timestamp) return '';

  const date = parseUtcTimestamp(timestamp);

  if (isNaN(date.getTime())) return '';

  return date.toLocaleDateString('en-US', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  });
};

/**
 * Format a UTC timestamp to local timezone string with time only
 * @param timestamp - UTC timestamp from backend
 * @returns Formatted local time string
 */
export const formatTime = (timestamp: string | Date | undefined): string => {
  if (!timestamp) return '';

  const date = parseUtcTimestamp(timestamp);

  if (isNaN(date.getTime())) return '';

  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  });
};
