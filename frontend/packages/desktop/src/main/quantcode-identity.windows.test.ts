import { expect, test } from "bun:test"
import { execFile } from "node:child_process"
import { createHash } from "node:crypto"
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { promisify } from "node:util"
import { connect, disconnect, importKey, inspect } from "./quantcode-identity"

test.skipIf(process.platform !== "win32" || process.env.QUANTCODE_WINDOWS_SSH_QA !== "1")(
  "Windows OpenSSH imports a disposable key and completes real agent signing, verification and logout",
  async () => {
    const run = promisify(execFile)
    const ssh = (name: string) => join(process.env.SystemRoot!, "System32", "OpenSSH", `${name}.exe`)
    const dir = await mkdtemp(join(tmpdir(), "quantcode-windows-ssh-"))
    const key = join(dir, "identity")
    await run(ssh("ssh-keygen"), ["-t", "ed25519", "-N", "", "-C", "quantcode-ci", "-f", key])
    const publicKey = (await readFile(`${key}.pub`, "utf8")).trim()
    const fingerprint = "SHA256:" + createHash("sha256").update(Buffer.from(publicKey.split(/\s+/)[1], "base64")).digest("base64").replace(/=+$/, "")
    const nonce = JSON.stringify({ purpose: "quantcode-login", group: "factor", nonce: "q".repeat(43) })
    const summary = { status: "connected", actor_id: "windows-ci", session_id: "a".repeat(32), fingerprint,
      group: "factor", groups: ["factor"], expires_at: new Date(Date.now() + 60000).toISOString(), execution_status: "disconnected" }
    let connected = false
    let verified = false
    const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
      const route = new URL(request.url).pathname
      if (route.endsWith("/identities")) return Response.json({ identities: [{ id: "qa-key", label: "Windows QA", fingerprint,
        host: "127.0.0.1", user: "SSH agent", group: "factor", groups: ["factor"] }], session: connected ? summary : null })
      if (route.endsWith("/identity/challenge")) return Response.json({ challenge_id: "b".repeat(32), public_key: publicKey,
        fingerprint, nonce, ttl_seconds: 60, gateway_origin: "https://gateway.example" })
      if (route.endsWith("/identity/verify")) {
        const body = await request.json() as { challenge_id: string; signature: string }
        expect(Object.keys(body).sort()).toEqual(["challenge_id", "signature"])
        expect(body.challenge_id).toBe("b".repeat(32))
        await writeFile(join(dir, "signature"), body.signature)
        await writeFile(join(dir, "allowed-signers"), `qa-member ${publicKey}\n`)
        const verify = Bun.spawn([ssh("ssh-keygen"), "-Y", "verify", "-f", join(dir, "allowed-signers"),
          "-I", "qa-member", "-n", "quantcode", "-s", join(dir, "signature")], {
          stdin: new TextEncoder().encode(nonce), stdout: "pipe", stderr: "pipe",
        })
        const [code, error] = await Promise.all([verify.exited, new Response(verify.stderr).text()])
        expect(code, error).toBe(0)
        verified = true
        connected = true
        return Response.json(summary)
      }
      if (route.endsWith("/identity/logout")) { connected = false; return Response.json({ status: "disconnected" }) }
      return new Response(null, { status: 404 })
    } })
    try {
      const connection = { url: server.url.origin }
      expect(await importKey(connection, key)).toEqual({ fingerprint })
      expect((await inspect(connection)).session).toBeNull()
      expect(await connect(connection, {}, "qa-key")).toEqual(summary)
      expect(verified).toBe(true)
      expect((await inspect(connection)).session?.fingerprint).toBe(fingerprint)
      expect(await disconnect(connection)).toEqual({ status: "disconnected", execution_status: "disconnected" })
      expect((await inspect(connection)).session).toBeNull()
    } finally {
      await server.stop(true)
      await run(ssh("ssh-add"), ["-d", `${key}.pub`]).catch(() => {})
      await rm(dir, { recursive: true, force: true })
    }
  }, 60000,
)
