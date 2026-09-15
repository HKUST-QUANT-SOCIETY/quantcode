import { execFile } from 'node:child_process'
import { access } from 'node:fs/promises'
import { win32 } from 'node:path'
import { promisify } from 'node:util'
import type { QuantCodeSshAgentStatus } from '@opencode-ai/app/identity'

const exec = promisify(execFile)
const defaults = {
  platform: process.platform,
  systemRoot: process.env.SystemRoot,
  exists: (file: string) => access(file).then(() => true, () => false),
  run: async (file: string, args: string[], timeout: number) => {
    const result = await exec(file, args, { encoding: 'utf8', timeout, maxBuffer: 262144, windowsHide: true })
    return result.stdout
  },
}

// Only this fixed service operation crosses the Windows elevation boundary.
// No selected filename, renderer input, shell profile or temporary script is used.
export const windowsAgentRepair = `$ErrorActionPreference = 'Stop'
try {
  $service = Get-Service -Name 'ssh-agent' -ErrorAction SilentlyContinue
  if ($null -eq $service) { exit 11 }
  Set-Service -Name 'ssh-agent' -StartupType Automatic
  Start-Service -Name 'ssh-agent'
  $service.WaitForStatus('Running', [TimeSpan]::FromSeconds(10))
  exit 0
} catch { exit 20 }`

export const windowsAgentStart = `$ErrorActionPreference = 'Stop'
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
${windowsAgentRepair}
}
try {
  $child = Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -Verb RunAs -WindowStyle Hidden -Wait -PassThru -ErrorAction Stop -ArgumentList @('-NoProfile', '-NonInteractive', '-EncodedCommand', '${Buffer.from(windowsAgentRepair, 'utf16le').toString('base64')}')
  exit $child.ExitCode
} catch {
  $failure = $_.Exception
  while ($null -ne $failure) {
    if ($failure.NativeErrorCode -eq 1223) { exit 23 }
    $failure = $failure.InnerException
  }
  exit 24
}`

export const windowsAgentInspect = `$ErrorActionPreference = 'Stop'
$service = Get-Service -Name 'ssh-agent' -ErrorAction SilentlyContinue
if ($null -eq $service) { Write-Output 'missing'; exit 0 }
Write-Output ([string]$service.Status)`

class AgentError extends Error {
  constructor(readonly state: 'missing-client' | 'unavailable' | 'permission' | 'timeout', message: string) { super(message) }
}

export function createSshAgentService(runtime = defaults) {
  let starting: Promise<QuantCodeSshAgentStatus> | undefined
  const platform = runtime.platform === 'win32' ? 'windows' : runtime.platform === 'darwin' ? 'macos' : 'linux'
  const executable = (name: 'ssh' | 'ssh-add' | 'ssh-keygen' | 'powershell') => {
    if (runtime.platform !== 'win32') return `/usr/bin/${name}`
    if (!runtime.systemRoot || !win32.isAbsolute(runtime.systemRoot)) throw new AgentError('missing-client', '无法定位 Windows OpenSSH 客户端，请检查系统组件。')
    return name === 'powershell'
      ? win32.join(runtime.systemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
      : win32.join(runtime.systemRoot, 'System32', 'OpenSSH', `${name}.exe`)
  }
  const powershell = (script: string, timeout: number) => runtime.run(executable('powershell'),
    ['-NoProfile', '-NonInteractive', '-EncodedCommand', Buffer.from(script, 'utf16le').toString('base64')], timeout)
  const read = async () => {
    if (runtime.platform === 'win32' && !(await Promise.all((['ssh', 'ssh-add', 'ssh-keygen'] as const).map(name => runtime.exists(executable(name))))).every(Boolean)) {
      throw new AgentError('missing-client', '缺少 Windows OpenSSH 客户端，请在系统“可选功能”中安装 OpenSSH 客户端。')
    }
    return runtime.run(executable('ssh-add'), ['-L'], 5000).catch((cause: unknown) => {
      const error = cause as NodeJS.ErrnoException & { stdout?: string; stderr?: string; killed?: boolean }
      if (Number(error.code) === 1 && /The agent has no identities\.?/i.test(`${error.stdout ?? ''}\n${error.stderr ?? ''}`)) return ''
      if (error.code === 'ENOENT') throw new AgentError('missing-client', '找不到系统 OpenSSH 客户端，请安装后重试。')
      if (error.code === 'EACCES' || error.code === 'EPERM') throw new AgentError('permission', '系统 OpenSSH 客户端无法执行，请检查本机访问权限。')
      if (error.killed || error.code === 'ETIMEDOUT') throw new AgentError('timeout', '系统 SSH Agent 响应超时，请检查状态后重试。')
      throw new AgentError('unavailable', '无法连接系统 SSH Agent，请检查并启用本机 SSH Agent。')
    })
  }
  const status = async (): Promise<QuantCodeSshAgentStatus> => {
    const failure = await read().then(() => undefined, cause => cause as Error)
    if (!failure) return { platform, status: 'ready', message: 'SSH Agent 已就绪。' }
    if (failure instanceof AgentError && failure.state === 'missing-client') return { platform, status: 'missing-client', message: failure.message }
    if (failure instanceof AgentError && (failure.state === 'permission' || failure.state === 'timeout')) return { platform, status: 'unavailable', message: failure.message }
    if (platform !== 'windows') return { platform, status: 'unavailable', message: failure.message }
    const service = await powershell(windowsAgentInspect, 8000).then(value => value.trim(), () => '')
    if (service === 'missing') return { platform, status: 'missing-service', message: 'Windows 缺少 SSH Agent 服务，请在系统“可选功能”中安装或修复 OpenSSH 客户端。' }
    if (service === 'Stopped' || service === 'StartPending' || service === 'StopPending') return {
      platform, status: 'stopped', message: 'Windows SSH Agent 尚未启动。点击下方按钮，在系统授权窗口确认后即可继续登录。',
    }
    return { platform, status: 'unavailable', message: service === 'Running'
      ? 'Windows SSH Agent 已运行，但应用无法连接。请退出并重新打开 QuantCode，再检查本机 SSH 身份。'
      : failure.message }
  }
  const start = (): Promise<QuantCodeSshAgentStatus> => {
    if (starting) return starting
    starting = (async () => {
      const before = await status()
      if (before.status === 'ready') return before
      if (before.platform !== 'windows' || before.status !== 'stopped') return before
      const failure = await powershell(windowsAgentStart, 90000).then(() => undefined, cause => cause as NodeJS.ErrnoException)
      // The UAC helper can finish just as the caller times out; trust the agent
      // probe, not the helper's exit code, before resuming any login operation.
      const after = await status()
      if (after.status === 'ready') return after
      if (Number(failure?.code) === 23) throw new Error('已取消 Windows 系统授权，SSH Agent 尚未启动。可以再次点击启用。')
      if (failure) throw new Error('Windows 未能启动 SSH Agent，请确认系统授权，或请本机管理员启用该服务后重新检查。')
      return after
    })().finally(() => { starting = undefined })
    return starting
  }
  return { read, status, start }
}

export const sshAgent = createSshAgentService()
