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
export type QuantCodeDesktopIdentity = {
  inspect(server: QuantCodeIdentityServer): Promise<QuantCodeIdentityInspection>
  connect(input: QuantCodeIdentityServer & { identityId?: string }): Promise<QuantCodeIdentitySession>
  importKey(server: QuantCodeIdentityServer): Promise<{ fingerprint: string } | null>
  disconnect(server: QuantCodeIdentityServer): Promise<QuantCodeIdentityDisconnected>
  /** Cancels a pending handshake; it does not revoke an already issued login. */
  cancel(server: QuantCodeIdentityServer): Promise<void>
}
