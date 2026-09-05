export function forwardArgvDeepLinks(
  argv: readonly string[],
  protocol: string,
  emit: (urls: string[]) => void,
): string[] {
  const urls = argv.filter((arg) => arg.startsWith(`${protocol}://`))
  if (urls.length > 0) emit(urls)
  return urls
}
