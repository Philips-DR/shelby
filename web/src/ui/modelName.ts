// The model's name as a person reads it. Pure, so it can be tested.

/** "us.anthropic.claude-opus-4-6-v1" -> "Opus 4.6"; "claude-opus-5" -> "Opus 5". The full id is the tooltip. */
export function modelName(id: string): string {
  // A second number only when it is a minor version (one or two digits, not the start of a date like -20250514).
  const match = /claude-([a-z]+)-(\d+)(?:-(\d{1,2})(?!\d))?/.exec(id)
  if (!match) return id || 'Assistant'
  return `${match[1]![0]!.toUpperCase()}${match[1]!.slice(1)} ${match[2]}${match[3] ? `.${match[3]}` : ''}`
}
