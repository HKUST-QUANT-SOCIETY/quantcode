export function draftHref(draftID: string, prompt?: string, options?: { submit?: boolean }) {
  const href = `/new-session?draftId=${encodeURIComponent(draftID)}`
  const withPrompt = prompt ? `${href}&prompt=${encodeURIComponent(prompt)}` : href
  return options?.submit ? `${withPrompt}&submit=true` : withPrompt
}
