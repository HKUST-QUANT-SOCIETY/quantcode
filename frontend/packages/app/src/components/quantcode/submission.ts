export type QuantCodeSubmissionHandler = (content: string) => void | boolean | Promise<boolean | void>

export function submitQuantCodeInstruction(handler: QuantCodeSubmissionHandler, content: string) {
  return Promise.resolve()
    .then(() => handler(content))
    .then(
      (accepted) => (accepted === false ? "unavailable" : "accepted"),
      () => "failed" as const,
    )
}
