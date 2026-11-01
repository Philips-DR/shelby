// Which colour means which tool, everywhere. Colour follows the entity, never its rank: filtering a
// chart to two tools must not repaint them.
//
// The eight hues and their order are the validated categorical palette (dataviz): the slot order is
// what keeps neighbours distinguishable under colour-blindness, so it is never rearranged. Values
// live in styles/tokens.css as --s1..--s8, stepped separately for the dark surface.
//
// Five tools take slots 1-5, consecutively (the validator checked neighbours in that order). Slot 4 is
// yellow, which is nearly the UI's warning colour, so it goes to the assistant itself (memory, drafts),
// whose calls are rarely the point, and audiobook takes magenta: a tool's bars must never look like a
// warning. The two tools with no page of their own, apply-ai and web-ai, take slots 6 and 7 in the same
// order. Slot 6 is a green close to the UI's "ok", so a tool that wears it is always named and iconed beside
// it, never told apart by colour alone (rule 3). Slot 8 is red, which is the UI's "bad", and stays unused.
// Anything unknown is "Other" (a neutral grey), never a generated ninth hue.

export const TOOLS = ['meet-ai', 'docu-ai', 'mail-ai', 'assistant', 'audiobook', 'apply-ai', 'web-ai'] as const
export type ToolName = (typeof TOOLS)[number]

export const TOOL_LABEL: Record<ToolName, string> = {
  'meet-ai': 'Meetings',
  'docu-ai': 'Documents',
  'mail-ai': 'Mail',
  audiobook: 'Audiobooks',
  assistant: 'Assistant',
  'apply-ai': 'Applications',
  'web-ai': 'Web',
}

/** "meet_ai__generate_notes" -> "meet-ai"; local tools ("assistant__remember") -> "assistant". */
export function toolOf(qualified: string): string {
  return (qualified.split('__')[0] ?? '').replace(/_/g, '-')
}

export const isTool = (name: string): name is ToolName => (TOOLS as readonly string[]).includes(name)

/** A CSS colour for a tool: its fixed slot, or the neutral for anything else. */
export const toolColor = (name: string): string => {
  const index = (TOOLS as readonly string[]).indexOf(name)
  return index >= 0 ? `var(--s${index + 1})` : 'var(--s-other)'
}

export const toolName = (name: string): string => (isTool(name) ? TOOL_LABEL[name] : name)
