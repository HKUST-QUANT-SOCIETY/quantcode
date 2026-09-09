import { open, lstat, realpath } from "node:fs/promises"
import { constants } from "node:fs"
import { isAbsolute } from "node:path"

/** Read the descriptor we validated, then ensure the name still refers to it.
 * Shared by host-owned credentials and workspace grants. Never log contents. */
export async function readPrivateFile(filename: string, maxBytes = 16384): Promise<string> {
  return readFile(filename, maxBytes, false)
}

/** For explicitly configured public host Markdown only. Callers must first
 * constrain the path to a trusted install root, never a research workspace. */
export async function readHostFile(filename: string, maxBytes = 262144): Promise<string> {
  return readFile(filename, maxBytes, true)
}

async function readFile(filename: string, maxBytes: number, publicText: boolean): Promise<string> {
  if (!isAbsolute(filename)) throw new Error("Host configuration path must be absolute")
  const canonical = await realpath(filename)
  const handle = await open(filename, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0))
  try {
    const info = await handle.stat()
    if (!info.isFile() || info.nlink > 1 || info.size > maxBytes || (process.platform !== "win32" &&
        (info.mode & (publicText ? 0o022 : 0o077) || (process.getuid && info.uid !== process.getuid() && !(publicText && info.uid === 0))))) {
      throw new Error("Host configuration must be a private regular file")
    }
    const text = await handle.readFile("utf8")
    const after = await handle.stat()
    const linked = await lstat(filename)
    if (Buffer.byteLength(text, "utf8") > maxBytes || linked.isSymbolicLink() || (await realpath(filename)) !== canonical ||
        linked.dev !== info.dev || linked.ino !== info.ino || linked.size !== after.size ||
        linked.mtimeMs !== after.mtimeMs || info.size !== after.size ||
        info.mtimeMs !== after.mtimeMs || info.ctimeMs !== after.ctimeMs) {
      throw new Error("Host configuration changed while being read")
    }
    return text
  } finally {
    await handle.close()
  }
}
