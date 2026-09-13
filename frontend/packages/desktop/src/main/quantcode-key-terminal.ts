import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { isAbsolute, win32 } from 'node:path'
import { systemSshExecutable } from './quantcode-ssh-login'

const run = promisify(execFile)
export function unlockCommand(file: string, windows = process.platform === 'win32', agentSocket = process.env.SSH_AUTH_SOCK) {
  if (!(windows ? win32.isAbsolute(file) : isAbsolute(file)) || file.includes('\0')) throw new Error('请先选择本地私钥。')
  const executable = systemSshExecutable('ssh-add')
  if (windows) return `${agentSocket ? `$env:SSH_AUTH_SOCK = '${agentSocket.replace(/'/g, "''")}'; ` : ''}& '${executable.replace(/'/g, "''")}' '${file.replace(/'/g, "''")}'`
  return `${agentSocket ? `SSH_AUTH_SOCK='${agentSocket.replace(/'/g, "'\\''")}' ` : ''}${executable} '${file.replace(/'/g, "'\\''")}'`
}

export async function openKeyTerminal(file: string) {
  const command = unlockCommand(file)
  if (process.platform === 'darwin') {
    await run('/usr/bin/osascript', ['-e', 'on run argv\ntell application "Terminal"\nactivate\ndo script (item 1 of argv)\nend tell\nend run', command], { timeout: 10000 })
    return
  }
  if (process.platform === 'win32') {
    const encoded = Buffer.from(command, 'utf16le').toString('base64')
    await run('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
      `Start-Process powershell.exe -ArgumentList '-NoExit','-NoProfile','-EncodedCommand','${encoded}'`], { timeout: 10000, windowsHide: true })
    return
  }
  throw new Error('请在系统终端运行 ssh-add 解锁所选私钥，然后重新探测。')
}
