import { lookup } from "node:dns"
import { Schema } from "effect"
import { WorkspaceRoutingQueryFields } from "../middleware/workspace-routing"

export const ProxyModelsQuery = Schema.Struct({
  ...WorkspaceRoutingQueryFields,
  url: Schema.String,
}).annotate({ identifier: "ProxyModelsQuery" })

export const ProxyModelsResponse = Schema.Struct({
  ok: Schema.Boolean,
  reachable: Schema.Boolean,
  status: Schema.optionalKey(Schema.Number),
  models: Schema.optionalKey(Schema.Array(Schema.String)),
}).annotate({ identifier: "ProxyModelsResponse" })

export class ProxyModelsUrlError extends Error {}

export type LookupAddresses = (host: string) => Promise<string[]>

export type ProxyModelsProbe =
  | { ok: false; reachable: false }
  | { ok: true; reachable: true; status: number; models?: string[] }

export const PROXY_MODELS_TIMEOUT_MS = 10_000

/**
 * True when the address is an IP literal in a range the proxy must never talk
 * to: loopback, unspecified, private, link-local, CGNAT-free ranges reserved
 * for local use, and IPv6 loopback / unique-local / link-local. Non-IP strings
 * (regular hostnames) are always false here; they are re-checked after DNS
 * resolution.
 */
export function isForbiddenIP(address: string): boolean {
  const value = address.toLowerCase().replace(/%.*$/, "").replace(/^\[/, "").replace(/\]$/, "")
  if (value.includes(":")) {
    const groups = expandIPv6(value)
    return groups !== undefined && forbiddenIPv6(groups)
  }
  return isForbiddenIPv4(value)
}

/** Expands an IPv6 address (with `::` compression and an optional IPv4 tail) into 8 16-bit groups. */
function expandIPv6(value: string): number[] | undefined {
  let rest = value
  const v4tail = /(?:^|:)(\d{1,3}(?:\.\d{1,3}){3})$/.exec(value)
  if (v4tail) {
    const octets = v4tail[1].split(".").map(Number)
    if (octets.some((octet) => octet > 255)) return undefined
    rest = `${value.slice(0, v4tail.index + 1)}${((octets[0] << 8) | octets[1]).toString(16)}:${(
      (octets[2] << 8) | octets[3]
    ).toString(16)}`
  }
  const halves = rest.split("::")
  if (halves.length > 2) return undefined
  const head = (halves[0] ? halves[0].split(":") : []).map((group) => (/^[0-9a-f]{1,4}$/.test(group) ? parseInt(group, 16) : -1))
  const tail = (halves.length === 2 && halves[1] ? halves[1].split(":") : []).map((group) =>
    /^[0-9a-f]{1,4}$/.test(group) ? parseInt(group, 16) : -1,
  )
  if (head.length + tail.length > 8 || [...head, ...tail].some((group) => group < 0)) return undefined
  return [...head, ...new Array(8 - head.length - tail.length).fill(0), ...tail]
}

function forbiddenIPv6(groups: number[]): boolean {
  if (groups.every((group) => group === 0)) return true // :: unspecified
  if (groups.slice(0, 7).every((group) => group === 0) && groups[7] === 1) return true // ::1 loopback
  if (groups.slice(0, 5).every((group) => group === 0) && groups[5] === 0xffff) {
    // ::ffff:x:x IPv4-mapped — apply the IPv4 rules to the embedded address
    return forbiddenIPv4Octets(groups[6] >> 8, groups[6] & 0xff)
  }
  if (groups[0] >= 0xfe80 && groups[0] <= 0xfebf) return true // fe80::/10 link-local
  if (groups[0] >= 0xfc00 && groups[0] <= 0xfdff) return true // fc00::/7 unique local
  return false
}

function forbiddenIPv4Octets(first: number, second: number): boolean {
  if (first === 0 || first === 10 || first === 127) return true // unspecified / private / loopback
  if (first === 169 && second === 254) return true // link-local
  if (first === 172 && second >= 16 && second <= 31) return true // private
  if (first === 192 && second === 168) return true // private
  return false
}

function isForbiddenIPv4(value: string): boolean {
  const parts = value.split(".")
  if (parts.length !== 4 || parts.some((part) => !/^\d{1,3}$/.test(part))) return false
  const octets = parts.map(Number)
  if (octets.some((octet) => octet > 255)) return false
  return forbiddenIPv4Octets(octets[0], octets[1])
}

/**
 * Static, DNS-free validation of a probe target. Only https, credential-free
 * URLs pointing at public, non-local hosts are accepted.
 */
export function validateProxyModelsURL(input: string): URL {
  let url: URL
  try {
    url = new URL(input)
  } catch {
    throw new ProxyModelsUrlError("invalid URL")
  }
  if (url.protocol !== "https:") throw new ProxyModelsUrlError("only https URLs are allowed")
  if (url.username || url.password) throw new ProxyModelsUrlError("URL credentials are not allowed")
  const host = url.hostname.toLowerCase()
  if (host === "localhost" || host.endsWith(".localhost") || host.endsWith(".local")) {
    throw new ProxyModelsUrlError("local hostnames are not allowed")
  }
  if (isForbiddenIP(host)) throw new ProxyModelsUrlError("private and loopback addresses are not allowed")
  let decodedPath = url.pathname
  try {
    decodedPath = decodeURIComponent(url.pathname)
  } catch {}
  if (url.pathname.includes("..") || decodedPath.includes("..")) {
    throw new ProxyModelsUrlError("path traversal is not allowed")
  }
  return url
}

export function lookupAddresses(host: string): Promise<string[]> {
  return new Promise((resolve, reject) => {
    lookup(host, { all: true, verbatim: true }, (error, addresses) => {
      if (error) reject(error)
      else resolve(addresses.map((entry) => entry.address))
    })
  })
}

function extractModelIDs(body: unknown): string[] {
  const list = Array.isArray((body as { data?: unknown })?.data)
    ? ((body as { data: unknown[] }).data as unknown[])
    : Array.isArray(body)
      ? body
      : []
  return Array.from(
    new Set(
      list
        .map((item) => (typeof item === "string" ? item : (item as { id?: unknown })?.id))
        .filter((id): id is string => typeof id === "string" && id.trim().length > 0)
        .map((id) => id.trim()),
    ),
  )
}

export type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>

/**
 * Credential-free probe of a provider model list endpoint. No caller input
 * other than the validated URL reaches the target: no cookies, no API keys,
 * no forwarded headers. Any HTTP response (including 401/403) means the
 * endpoint exists; model IDs are only extracted from 2xx JSON bodies.
 */
export async function probeProxyModels(url: URL, doFetch: FetchLike = globalThis.fetch): Promise<ProxyModelsProbe> {
  let response: Response
  try {
    // redirect: "error" keeps a validated https target from being followed to
    // an http or private address via a 3xx hop.
    response = await doFetch(url, {
      redirect: "error",
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(PROXY_MODELS_TIMEOUT_MS),
    })
  } catch {
    return { ok: false, reachable: false }
  }
  if (!response.ok) return { ok: true, reachable: true, status: response.status }
  const body: unknown = await response.json().catch(() => undefined)
  return { ok: true, reachable: true, status: response.status, models: extractModelIDs(body) }
}
