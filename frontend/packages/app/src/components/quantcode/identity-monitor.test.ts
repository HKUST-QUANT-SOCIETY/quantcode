import { expect, test } from 'bun:test'
import { monitorIdentity } from './identity-monitor'

test('network failure retains the ability to revalidate the same identity', async () => {
  let reachable = false
  const states: string[] = []
  const monitor = monitorIdentity({
    read: async () => { if (!reachable) throw new Error('offline'); return 'member' },
    ready: value => states.push(value), unavailable: () => states.push('unknown'),
  })
  try {
    await monitor.refresh()
    reachable = true
    await monitor.refresh()
    expect(states).toEqual(['unknown', 'member'])
  } finally { monitor.dispose() }
})

test('a disposed server cannot overwrite the next server with a late authority result', async () => {
  const response = Promise.withResolvers<string>()
  const states: string[] = []
  const monitor = monitorIdentity({ read: () => response.promise, ready: value => states.push(value), unavailable: () => states.push('error') })
  const pending = monitor.refresh()
  monitor.dispose()
  response.resolve('old server')
  await pending
  expect(states).toEqual([])
})

test('concurrent recovery events coalesce without losing the subsequent recheck', async () => {
  const first = Promise.withResolvers<string>()
  let calls = 0
  const monitor = monitorIdentity({ read: async () => ++calls === 1 ? first.promise : 'recovered', ready: () => {}, unavailable: () => {} })
  try {
    const initial = monitor.refresh()
    await monitor.refresh(); await monitor.refresh()
    expect(calls).toBe(1)
    first.resolve('old')
    await initial
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(calls).toBe(2)
  } finally { monitor.dispose() }
})
