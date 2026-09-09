/** Transport context is attached by the native tool boundary, never copied
 * from model arguments or plugin metadata. It carries no credential. */
export type NativeCall = {
  version: 1
  server: string
  login_session_id: string
  native_session_id: string
  root_session_id: string
  message_id: string
  call_id: string
  catalog_digest: string
  arguments_json: string
  arguments_digest: string
  gate_id?: string
  operation_digest?: string
}

const calls = new WeakMap<object, NativeCall>()
export function bind<T extends object>(options: T, context: NativeCall): T {
  const scoped = { ...options }
  calls.set(scoped, Object.freeze({ ...context }))
  return scoped
}
export function read(options: object) { return calls.get(options) }
export * as QuantCodeMcpContext from "./mcp-context"
