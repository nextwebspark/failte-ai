/** One CSV cell: quoted, with inner quotes doubled. */
export function csvCell(value: string): string {
  return `"${value.replace(/"/g, '""')}"`;
}

/** The download's column names, in plain words. */
export const CSV_HEADERS = ['Phone number', 'Call outcome', 'Call length (seconds)', 'Link to call'];
