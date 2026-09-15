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
export type QuantCodeSshAgentStatus = {
  platform: 'windows' | 'macos' | 'linux'
  status: 'ready' | 'stopped' | 'missing-client' | 'missing-service' | 'unavailable'
  message: string
}
/** 组织 SSH 登录向导：成员只提供本地私钥，服务器地址内置。 */
export type QuantCodeSshLoginServer = { id: string; label: string; host: string; username: string; groups: QuantCodeIdentityGroup[] }
export type QuantCodeSshAdministrator = { id: string; label: string; host: string; username: string; systemGroups: string[] }
export const sshUsernameSources = { input: '本次输入', remembered: '已确认记录', config: 'SSH 配置', filename: '文件名', route: '工作区登记', 'workspace-cache': '上次工作区发现', missing: '未确定' } as const
export type QuantCodeSshUsernameSource = keyof typeof sshUsernameSources
/** SSH connection metadata belongs to the same verified administrator login. */
export type QuantCodeServerAdminSession = { serverId: string; serverLabel: string; username: string; fingerprint: string; expires_at: string }
export type QuantCodeServerAdminStatus = { session: QuantCodeServerAdminSession; report: string }
export type QuantCodeSshLoginScan = {
  username: string
  needsUsername?: boolean
  servers: QuantCodeSshLoginServer[]
  administrators?: QuantCodeSshAdministrator[]
  failed: { id: string; reason: string; username?: string; usernameSource?: QuantCodeSshUsernameSource }[]
}
export type QuantCodeSshConnection = { url: string; username: string; password: string; displayName: string; organizationAdmin?: boolean; managedId?: string; previousUrls?: string[]; verifiedAt?: number }
export type QuantCodeConnectionState = { server: string; url: string; state: "connecting" | "connected" | "reconnecting" | "offline" | "closed"; generation: number; reason?: string }
export type QuantCodeSshLoginChoice = { serverId: string; group: QuantCodeIdentityGroup } | { serverId: string; administrator: "servers" | "organization" }
export type QuantCodeSshLoginResult = { mode?: "member" | "organization-admin"; admin?: QuantCodeServerAdminSession; connection: QuantCodeSshConnection; session: QuantCodeIdentitySession }
export type QuantCodeDesktopIdentity = {
  sshProgress?(): Promise<string[]>
  sshSelectKey?(): Promise<boolean>
  sshCancel?(): Promise<void>
  sshUnlockKey?(): Promise<void>
  sshAgentStatus?(): Promise<QuantCodeSshAgentStatus>
  sshStartAgent?(): Promise<QuantCodeSshAgentStatus>
  sshOpenAgentSettings?(): Promise<void>
  sshAgentKeys?(): Promise<{ fingerprint: string; label: string }[]>
  sshSelectAgent?(input: { fingerprint: string }): Promise<void>
  sshResolve?(): Promise<QuantCodeSshLoginResult | null>
  sshExitAttempt?(): Promise<void>
  sshAcknowledge?(input: { sessionId: string }): Promise<void>
  sshConnectionState?(server: QuantCodeIdentityServer): Promise<QuantCodeConnectionState | null>
  sshReconnect?(server: QuantCodeIdentityServer): Promise<void>
  onSshConnectionState?(listener: (state: QuantCodeConnectionState) => void): () => void
  inspect(server: QuantCodeIdentityServer): Promise<QuantCodeIdentityInspection>
  connect(input: QuantCodeIdentityServer & { identityId?: string }): Promise<QuantCodeIdentitySession>
  importKey(server: QuantCodeIdentityServer): Promise<{ fingerprint: string } | null>
  disconnect(server: QuantCodeIdentityServer): Promise<QuantCodeIdentityDisconnected>
  /** Cancels a pending handshake; it does not revoke an already issued login. */
  cancel(server: QuantCodeIdentityServer): Promise<void>
  /** 私钥路径只留在主进程；重试复用刚选的文件。 */
  sshScan(input: { chooseKey?: boolean; username?: string }): Promise<QuantCodeSshLoginScan | null>
  sshConnect(input: QuantCodeSshLoginChoice): Promise<QuantCodeSshLoginResult>
  sshAdminStatus(input?: { serverId?: string }): Promise<QuantCodeServerAdminStatus | null>
  sshAdminDisconnect(): Promise<void>
  /** 恢复隧道并检查既有会话，不重新签发登录。 */
  sshRestore(): Promise<{ connection: QuantCodeSshConnection; session: QuantCodeIdentitySession | null; admin?: QuantCodeServerAdminSession; needsLogin?: false; requiresConfirmation?: boolean }
    | { connection?: undefined; session?: undefined; admin?: undefined; needsLogin: true } | null>
}
