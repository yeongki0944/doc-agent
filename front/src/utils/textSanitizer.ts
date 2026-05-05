export function sanitizeListPasteText(value: string): string {
  return value
    .split(/\r?\n/)
    .map(line => line
      .replace(/^\s*[\u2022\u25E6\u25AA\u00B7]\s*\t?\s*/, '')
      .replace(/^\s*[-*]\s+/, '')
      .replace(/^\s*\d{1,2}[.)]\s+(?=\S)/, '')
      .trim())
    .filter(Boolean)
    .join('\n')
}
