/**
 * Timestamp utility functions for converting UTC timestamps to local timezone
 */

/**
 * Format a UTC timestamp to local timezone string
 * @param timestamp - UTC timestamp from backend (ISO format string or Date object)
 * @returns Formatted local time string
 */
export const formatTimestamp = (timestamp: string | Date | undefined): string => {
  if (!timestamp) return '';
  
  let date: Date;
  if (typeof timestamp === 'string') {
    date = new Date(timestamp);
  } else if (timestamp instanceof Date) {
    date = timestamp;
  } else {
    return '';
  }
  
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
  
  let date: Date;
  if (typeof timestamp === 'string') {
    date = new Date(timestamp);
  } else if (timestamp instanceof Date) {
    date = timestamp;
  } else {
    return '';
  }
  
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
  
  let date: Date;
  if (typeof timestamp === 'string') {
    date = new Date(timestamp);
  } else if (timestamp instanceof Date) {
    date = timestamp;
  } else {
    return '';
  }
  
  if (isNaN(date.getTime())) return '';
  
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  });
};
