/** Desktop GitHub connection returns status only; credentials never cross IPC. */
export type DesktopGitHubResult = {
  status: "connected" | "disconnected" | "authorizing" | "error"
  subject?: string
  host?: string
  code?: string
  url?: string
  error?: string
}
export type DesktopGitHub = {
  request(input: { server: string; mode?: "local" | "browser" | "cancel" }): Promise<DesktopGitHubResult>
}
