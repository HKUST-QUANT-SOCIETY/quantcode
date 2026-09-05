import { describe, expect, test } from "bun:test"
import {
  isForbiddenIP,
  lookupAddresses,
  probeProxyModels,
  validateProxyModelsURL,
  ProxyModelsUrlError,
} from "../../src/server/routes/instance/httpapi/groups/proxy-models"
import type { FetchLike } from "../../src/server/routes/instance/httpapi/groups/proxy-models"

function expectForbidden(input: string) {
  expect(() => validateProxyModelsURL(input)).toThrow(ProxyModelsUrlError)
}

describe("validateProxyModelsURL", () => {
  test("accepts public https URLs", () => {
    expect(validateProxyModelsURL("https://api.openai.com/v1/models").hostname).toBe("api.openai.com")
    expect(validateProxyModelsURL("https://8.8.8.8/v1/models").hostname).toBe("8.8.8.8")
    // 172.32.x.x is just outside the 172.16-31 private range
    expect(validateProxyModelsURL("https://172.32.0.1/v1/models").hostname).toBe("172.32.0.1")
  })

  test("rejects non-https schemes", () => {
    expectForbidden("http://api.openai.com/v1/models")
    expectForbidden("ftp://api.example.com/models")
  })

  test("rejects URLs with embedded credentials", () => {
    expectForbidden("https://user:pass@api.example.com/v1/models")
    expectForbidden("https://user@api.example.com/v1/models")
  })

  test("rejects local hostnames", () => {
    expectForbidden("https://localhost/v1/models")
    expectForbidden("https://api.localhost/v1/models")
    expectForbidden("https://printer.local/models")
  })

  test("rejects private, loopback and link-local IPv4 literals", () => {
    expectForbidden("https://127.0.0.1/v1/models")
    expectForbidden("https://10.1.2.3/v1/models")
    expectForbidden("https://172.16.0.1/v1/models")
    expectForbidden("https://172.31.255.255/v1/models")
    expectForbidden("https://192.168.1.1/v1/models")
    expectForbidden("https://169.254.169.254/latest/meta-data")
    expectForbidden("https://0.0.0.0/v1/models")
  })

  test("rejects loopback and IPv4-mapped IPv6 literals", () => {
    expectForbidden("https://[::1]/v1/models")
    expectForbidden("https://[::ffff:127.0.0.1]/v1/models")
    expectForbidden("https://[::ffff:10.0.0.1]/v1/models")
  })

  test("cannot smuggle dot-segment traversal past the URL parser", () => {
    // WHATWG URL parsing normalizes ".." and "%2e%2e" segments away before the
    // guard sees them; the guard's ".." check is defense-in-depth for other
    // parsers. Either way no dot-segment may survive validation.
    const inputs = [
      "https://api.example.com/../admin/models",
      "https://api.example.com/v1/%2e%2e/models",
    ]
    for (const input of inputs) {
      expect(validateProxyModelsURL(input).pathname.includes("..")).toBe(false)
    }
  })

  test("rejects invalid URLs", () => {
    expectForbidden("not a url")
    expectForbidden("https://")
  })
})

describe("isForbiddenIP", () => {
  test("flags forbidden ranges", () => {
    expect([
      "127.0.0.1",
      "10.0.0.1",
      "172.16.0.1",
      "172.31.255.255",
      "192.168.0.1",
      "169.254.0.1",
      "0.0.0.0",
      "::",
      "::1",
      "::ffff:127.0.0.1",
      "fe80::1",
      "febf::1",
      "fc00::1",
      "fd00::1",
    ].every((address) => isForbiddenIP(address))).toBe(true)
  })

  test("allows public addresses and plain hostnames", () => {
    expect([
      "8.8.8.8",
      "172.32.0.1",
      "2606:4700::1",
      "api.example.com",
      // hostnames that merely look like reserved hex prefixes
      "fcbarcelona.example.com",
      "fe80.example.com",
    ].every((address) => !isForbiddenIP(address))).toBe(true)
  })
})

describe("lookupAddresses", () => {
  // "localhost" resolves via /etc/hosts without network access; the proxy must
  // never forward requests to whatever it resolves to.
  test("resolves localhost to forbidden addresses", async () => {
    const addresses = await lookupAddresses("localhost")
    expect(addresses.length).toBeGreaterThan(0)
    expect(addresses.every((address) => isForbiddenIP(address))).toBe(true)
  })
})

describe("probeProxyModels", () => {
  const target = () => validateProxyModelsURL("https://api.example.com/v1/models")

  test("extracts model ids from a 2xx data-wrapped JSON body", async () => {
    const body = JSON.stringify({ data: [{ id: "gpt-4o" }, { id: "gpt-4o" }, { id: "claude-3" }] })
    const fetchMock: FetchLike = async () => new Response(body, { status: 200 })
    const result = await probeProxyModels(target(), fetchMock)
    expect(result).toEqual({ ok: true, reachable: true, status: 200, models: ["gpt-4o", "claude-3"] })
  })

  test("extracts model ids from a bare JSON array body", async () => {
    const fetchMock: FetchLike = async () => new Response(JSON.stringify([{ id: "m1" }, "m2"]), { status: 200 })
    const result = await probeProxyModels(target(), fetchMock)
    expect(result).toEqual({ ok: true, reachable: true, status: 200, models: ["m1", "m2"] })
  })

  test("treats 401/403 as reachable without leaking the body", async () => {
    const fetchMock: FetchLike = async () => new Response(JSON.stringify({ error: "secret" }), { status: 401 })
    const result = await probeProxyModels(target(), fetchMock)
    expect(result).toEqual({ ok: true, reachable: true, status: 401 })
    expect("models" in result).toBe(false)
  })

  test("omits models when a 2xx body is not JSON", async () => {
    const fetchMock: FetchLike = async () => new Response("<html>hello</html>", { status: 200 })
    const result = await probeProxyModels(target(), fetchMock)
    expect(result).toEqual({ ok: true, reachable: true, status: 200, models: [] })
  })

  test("reports network failures as unreachable", async () => {
    const fetchMock: FetchLike = async () => {
      throw new Error("connection refused")
    }
    const result = await probeProxyModels(target(), fetchMock)
    expect(result).toEqual({ ok: false, reachable: false })
  })

  test("reports timeouts as unreachable and passes an abort signal", async () => {
    let seenSignal: AbortSignal | null | undefined
    const fetchMock: FetchLike = async (_input, init) => {
      seenSignal = init?.signal
      throw new DOMException("The operation timed out", "TimeoutError")
    }
    const result = await probeProxyModels(target(), fetchMock)
    expect(result).toEqual({ ok: false, reachable: false })
    expect(seenSignal).toBeInstanceOf(AbortSignal)  })

  test("sends no credentials and refuses redirects", async () => {
    let seenInit: RequestInit | undefined
    const fetchMock: FetchLike = async (_input, init) => {
      seenInit = init
      return new Response(JSON.stringify({ data: [] }), { status: 200 })
    }
    await probeProxyModels(target(), fetchMock)
    const headers = new Headers(seenInit?.headers)
    expect(headers.get("authorization")).toBeNull()
    expect(headers.get("cookie")).toBeNull()
    expect(seenInit?.redirect).toBe("error")
  })
})
