#!/usr/bin/env bun

import { existsSync } from "node:fs"
import { delimiter, join } from "node:path"

const root = join(import.meta.dir, "..")
const backendRoot = process.env.QUANTCODE_ROOT ?? join(root, "..")
const pythonBin = join(backendRoot, ".venv", process.platform === "win32" ? "Scripts" : "bin")
const env = {
  ...process.env,
  OPENCODE_CHANNEL: "quantcode",
  QUANTCODE_ROOT: backendRoot,
  PATH: existsSync(pythonBin) ? `${pythonBin}${delimiter}${process.env.PATH ?? ""}` : process.env.PATH,
  QUANTCODE_BACKEND_ROOT: process.env.QUANTCODE_BACKEND_ROOT ?? join(root, ".."),
  MODELS_DEV_API_JSON:
    process.env.MODELS_DEV_API_JSON ?? join(root, "packages/opencode/test/tool/fixtures/models-api.json"),
}

const mode = Bun.argv[2] ?? "web"
if (mode !== "web" && mode !== "desktop") {
  console.error(`Unknown QuantCode development mode: ${mode}`)
  process.exit(2)
}

const commands =
  mode === "desktop"
    ? [["bun", "run", "--cwd", "packages/desktop", "dev"]]
    : [
        ["bun", "run", "--cwd", "packages/opencode", "--conditions=browser", "src/index.ts", "serve", "--port", "4096"],
        ["bun", "run", "--cwd", "packages/app", "dev", "--host", "127.0.0.1", "--port", "4444"],
      ]

const processes = commands.map((command) =>
  Bun.spawn(command, {
    cwd: root,
    env,
    stdin: "inherit",
    stdout: "inherit",
    stderr: "inherit",
  }),
)

let stopping = false
const stop = () => {
  if (stopping) return
  stopping = true
  for (const child of processes) child.kill()
}

process.on("SIGINT", stop)
process.on("SIGTERM", stop)

const result = await Promise.race(processes.map((child, index) => child.exited.then((code) => ({ code, index }))))
stop()
await Promise.allSettled(processes.map((child) => child.exited))

if (result.code !== 0) {
  console.error(`QuantCode development process ${result.index + 1} exited with code ${result.code}`)
}

process.exit(result.code)
