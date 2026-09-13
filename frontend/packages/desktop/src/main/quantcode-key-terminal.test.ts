import { expect, test } from 'bun:test'
import { unlockCommand } from './quantcode-key-terminal'

test('terminal unlock treats the selected filename as data', () => {
  expect(unlockCommand("/tmp/a'b;$(false).key", false)).toEndWith(" '/tmp/a'\\''b;$(false).key'")
  expect(unlockCommand("C:\\Keys\\a'b;$(false).key", true)).toContain("'C:\\Keys\\a''b;$(false).key'")
  expect(() => unlockCommand('relative.key', false)).toThrow()
  expect(unlockCommand('/tmp/key', false, "/tmp/agent'$(false)")).toStartWith("SSH_AUTH_SOCK='/tmp/agent'\\''$(false)' ")
})
