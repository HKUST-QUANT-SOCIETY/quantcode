/** Host-maintainer file publication shared by workspace and tool enrollment.
 * Deliberately not imported by model tools or HTTP routes. */
import { open, mkdir, rename, rm, lstat, realpath } from "node:fs/promises"
import path from "node:path"
import { randomUUID, createHash } from "node:crypto"
import { Flock } from "@opencode-ai/core/util/flock"
import { readPrivateFile } from "../src/quantcode/private-file"

export const digest = (value: string) => createHash("sha256").update(value).digest("hex")

export async function privateDirectory(directory: string) {
  if (!path.isAbsolute(directory)) throw new Error("Host directory must be absolute")
  // Do not treat POSIX mode bits as a Windows access-control check.
  if (process.platform === "win32") throw new Error("Host enrollment requires Windows ACL verification; publication is unavailable on this host")
  await mkdir(directory, { recursive: true, mode: 0o700 })
  const info = await lstat(directory)
  if (!info.isDirectory() || info.isSymbolicLink() || await realpath(directory) !== path.resolve(directory) ||
      info.mode & 0o077 || (process.getuid && info.uid !== process.getuid())) {
    throw new Error("Host directory must be canonical, private and owned by the host account")
  }
  return info
}

export async function readCurrent(filename: string, maxBytes: number) {
  return lstat(filename).then(() => readPrivateFile(filename, maxBytes), (error: NodeJS.ErrnoException) => {
    if (error.code === "ENOENT") return undefined
    throw error
  })
}

export async function writeNewPrivateFile(filename: string, content: string) {
  await privateDirectory(path.dirname(filename))
  const file = await open(filename, "wx", 0o600)
  try { await file.writeFile(content); await file.sync() } finally { await file.close() }
}

export async function updateHostFile(input: {
  filename: string
  expected: string
  maxBytes: number
  history: string
  update: (previous: string | undefined) => Promise<string>
}) {
  if (!path.isAbsolute(input.filename) || path.resolve(input.filename) !== input.filename || !/^(absent|[a-f0-9]{64})$/.test(input.expected)) {
    throw new Error("Absolute destination and exact expected digest (or absent) are required")
  }
  const directory = path.dirname(input.filename)
  const initial = await privateDirectory(directory)
  const history = path.join(directory, input.history)
  await privateDirectory(history)
  const locks = path.join(directory, ".publication-locks")
  await privateDirectory(locks)
  // Reuse the existing OpenCode lease; a dead publisher is not automatically
  // stolen. An operator first inspects the archive and current digest.
  return Flock.withLock(input.filename, async () => {
    const previous = await readCurrent(input.filename, input.maxBytes)
    if ((previous === undefined ? "absent" : digest(previous)) !== input.expected) {
      throw new Error("Host configuration changed; inspect its current digest before publishing")
    }
    const content = await input.update(previous)
    if (Buffer.byteLength(content, "utf8") > input.maxBytes) throw new Error("Host configuration exceeds the size limit")
    for (const value of [previous, content]) {
      if (value === undefined) continue
      const archive = path.join(history, `${digest(value)}.json`)
      const existing = await readCurrent(archive, input.maxBytes)
      if (existing === undefined) await writeNewPrivateFile(archive, value)
      else if (existing !== value) throw new Error("Archived configuration content mismatch")
    }
    const archived = await open(history, "r")
    try { await archived.sync() } finally { await archived.close() }
    const temporary = `${input.filename}.${randomUUID()}.tmp`
    try {
      await writeNewPrivateFile(temporary, content)
      const current = await privateDirectory(directory)
      if (current.dev !== initial.dev || current.ino !== initial.ino ||
          await readCurrent(input.filename, input.maxBytes) !== previous) {
        throw new Error("Host configuration changed during publication")
      }
      await rename(temporary, input.filename)
      const parent = await open(directory, "r")
      try { await parent.sync() } finally { await parent.close() }
      return { digest: digest(content) }
    } finally {
      await rm(temporary, { force: true })
    }
  }, { dir: locks, staleMs: Number.POSITIVE_INFINITY, timeoutMs: 5000 })
}
