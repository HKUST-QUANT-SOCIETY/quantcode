import { expect, test } from 'bun:test'
import { createSshAgentService, windowsAgentStart, windowsAgentRepair } from './quantcode-ssh-agent'

function failure(code: number | string, stdout = '', stderr = '') {
  return Object.assign(new Error('fixture process failure'), { code, stdout, stderr })
}

function fixture() {
  const calls: { file: string; args: string[]; script?: string }[] = []
  const state = { available: false, service: 'Stopped', missing: false, cancelled: false, startError: false, started: false }
  const manager = createSshAgentService({ platform: 'win32', systemRoot: 'C:\\Windows',
    exists: async () => !state.missing,
    run: async (file, args) => {
      const script = args.includes('-EncodedCommand') ? Buffer.from(args.at(-1)!, 'base64').toString('utf16le') : undefined
      calls.push({ file, args, script })
      if (file.endsWith('ssh-add.exe')) {
        if (state.available) throw failure(1, 'The agent has no identities.\r\n')
        throw failure(2, '', 'Error connecting to agent: No such file or directory')
      }
      if (script === windowsAgentStart) {
        state.started = true
        if (state.cancelled) throw failure(23)
        state.available = true
        // Simulate a helper timeout after the service has already started.
        if (state.startError) throw failure('ETIMEDOUT')
        return ''
      }
      return state.service + '\r\n'
    },
  })
  return { manager, state, calls }
}

test('empty running agent is ready; inspection never requests elevation', async () => {
  const { manager, state, calls } = fixture()
  state.available = true
  expect(await manager.read()).toBe('')
  expect((await manager.status()).status).toBe('ready')
  expect((await manager.start()).status).toBe('ready')
  expect(calls.every(call => call.file.endsWith('ssh-add.exe'))).toBe(true)
})

test('stopped Windows agent offers recovery and concurrent clicks share one elevated helper', async () => {
  const { manager, calls } = fixture()
  expect((await manager.status()).status).toBe('stopped')
  expect(calls.some(call => call.script === windowsAgentStart)).toBe(false)
  const [first, second] = await Promise.all([manager.start(), manager.start()])
  expect(first.status).toBe('ready')
  expect(second.status).toBe('ready')
  expect(calls.filter(call => call.script === windowsAgentStart)).toHaveLength(1)
  expect(calls.filter(call => call.script).every(call => call.file === 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe')).toBe(true)
})

test('missing client and missing service are distinct and do not try to elevate', async () => {
  for (const mode of ['client', 'service']) {
    const { manager, state, calls } = fixture()
    if (mode === 'client') state.missing = true
    else state.service = 'missing'
    expect((await manager.start()).status).toBe(mode === 'client' ? 'missing-client' : 'missing-service')
    expect(calls.some(call => call.script === windowsAgentStart)).toBe(false)
  }
})

test('cancelled UAC is actionable and a later explicit retry can recover', async () => {
  const { manager, state } = fixture()
  state.cancelled = true
  await expect(manager.start()).rejects.toThrow('已取消 Windows 系统授权')
  state.cancelled = false
  expect((await manager.start()).status).toBe('ready')
})

test('successful agent probe wins over a timed-out service helper', async () => {
  const { manager, state } = fixture()
  state.startError = true
  expect((await manager.start()).status).toBe('ready')
})

test('a running but inaccessible Windows agent is not diagnosed as stopped', async () => {
  const { manager, state } = fixture()
  state.service = 'Running'
  const result = await manager.start()
  expect(result.status).toBe('unavailable')
  expect(result.message).toContain('已运行')
  expect(state.started).toBe(false)
})

test('SSH execution failures are not mistaken for an empty agent', async () => {
  for (const code of ['ENOENT', 'EACCES', 'ETIMEDOUT', 1]) {
    const manager = createSshAgentService({ platform: 'darwin', systemRoot: undefined, exists: async () => true,
      run: async () => { throw failure(code, '', 'agent refused operation') } })
    await expect(manager.read()).rejects.toThrow()
    expect((await manager.status()).status).toBe(code === 'ENOENT' ? 'missing-client' : 'unavailable')
  }
})

test('Windows executable permission and timeout failures keep their specific diagnosis', async () => {
  for (const [code, message] of [['EACCES', '访问权限'], ['ETIMEDOUT', '响应超时']]) {
    const service = createSshAgentService({ platform: 'win32', systemRoot: 'C:\\Windows', exists: async () => true,
      run: async file => { expect(file).toEndWith('ssh-add.exe'); throw failure(code!) } })
    const result = await service.status()
    expect(result.status).toBe('unavailable')
    expect(result.message).toContain(message!)
  }
})

test('elevation uses only the embedded fixed service repair and no private-key or renderer data', () => {
  expect(windowsAgentStart).toContain(Buffer.from(windowsAgentRepair, 'utf16le').toString('base64'))
  expect(windowsAgentStart).toContain('-Verb RunAs')
  expect(windowsAgentRepair).toContain("Set-Service -Name 'ssh-agent' -StartupType Automatic")
  expect(windowsAgentRepair).not.toMatch(/ssh-add|private|Invoke-Expression|\.ps1|\$args/i)
})
