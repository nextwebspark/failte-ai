/** One CSV cell: quoted, with inner quotes doubled. A cell starting with = or @
 * is shown as text, so a spreadsheet never runs it as a formula. */
export function csvCell(value: string): string {
    const safe = /^[=@\t\r]/.test(value) ? `'${value}` : value;
    return `"${safe.replace(/"/g, '""')}"`;
}

/** The download's column names, in plain words. */
export const CSV_HEADERS = [
    'Date and time',
    'Agent',
    'Phone number',
    'Caller',
    'What happened',
    'What they wanted',
    'Call length (seconds)',
    'Link to call',
];
