/** Give the shell a controlling PTY inside the Linux sandbox. The outer PTY
 * remains a transport; Ctrl-C must stop the foreground job, not bubblewrap. */
export function terminalCommand(shell: string, args: readonly string[], platform = process.platform) {
  if (platform !== "linux") return { command: shell, args: [...args] }
  const command = [shell, ...args].map(value => "'" + value.replaceAll("'", "'\\''") + "'").join(" ")
  return { command: "/usr/bin/script", args: ["--quiet", "--return", "--flush", "--command", command, "/dev/null"] }
}
