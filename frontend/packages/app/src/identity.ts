/** Renderer-safe identity summaries. Tokens, local paths and signatures never
 * belong in this contract; the main process completes the signing handshake. */
export type QuantCodeIdentityServer = { server: string }
export type QuantCodeIdentityGroup = "fundamental" | "factor" | "model" | "risk" | "strategy" | "options" | "infra" | "agent"
export type QuantCodeIdentitySession = {
  status: "connected"
  actor_id: string
  session_id: string
  fingerprint: string
  group: QuantCodeIdentityGroup
  groups: QuantCodeIdentityGroup[]
  expires_at: string
  execution_status: "disconnected"
}
export type QuantCodeIdentityInspection = {
  identities: { id: string; label: string; fingerprint: string; host: string; user: string;
    group: QuantCodeIdentityGroup; groups: QuantCodeIdentityGroup[] }[]
  session: QuantCodeIdentitySession | null
}
export type QuantCodeIdentityDisconnected = { status: "disconnected"; execution_status: "disconnected" }
/** 组织 SSH 登录向导：成员只提供本地私钥，服务器地址内置。 */
export type QuantCodeSshLoginServer = { id: string; label: string; host: string; username: string; groups: string[] }
export type QuantCodeSshLoginScan = {
  username: string
  servers: QuantCodeSshLoginServer[]
  failed: { id: string; reason: "unreachable" | "not-enrolled" }[]
}
export type QuantCodeDesktopIdentity = {
  inspect(server: QuantCodeIdentityServer): Promise<QuantCodeIdentityInspection>
  connect(input: QuantCodeIdentityServer & { identityId?: string }): Promise<QuantCodeIdentitySession>
  importKey(server: QuantCodeIdentityServer): Promise<{ fingerprint: string } | null>
  disconnect(server: QuantCodeIdentityServer): Promise<QuantCodeIdentityDisconnected>
  /** Cancels a pending handshake; it does not revoke an already issued login. */
  cancel(server: QuantCodeIdentityServer): Promise<void>
  /** SSH 登录向导：选本地私钥 → 三台组织服务器探测 → 返回可达的 (组 × 服务器)。 */
  sshScan(input: { keyFile: string; username?: string }): Promise<QuantCodeSshLoginScan>
  sshProbe(input: { keyFile: string; username: string }): Promise<{ ok: true } | { ok: false; reason: string }>
}
