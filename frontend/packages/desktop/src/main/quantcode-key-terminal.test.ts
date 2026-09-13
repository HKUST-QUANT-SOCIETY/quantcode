import { expect, test } from 'bun:test'
import { unlockCommand } from './quantcode-key-terminal'

test('terminal unlock treats the selected filename as data', () => {
  expect(unlockCommand("/tmp/a'b;$(false).key", false)).toEndWith(" '/tmp/a'\\''b;$(false).key'")
  expect(unlockCommand("C:\\Keys\\a'b;$(false).key", true)).toContain("'C:\\Keys\\a''b;$(false).key'")
  expect(() => unlockCommand('relative.key', false)).toThrow()
})
