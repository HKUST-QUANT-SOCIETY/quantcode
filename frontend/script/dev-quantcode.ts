#!/usr/bin/env bun

import { existsSync } from "node:fs"
import { lstat } from "node:fs/promises"
import { delimiter, isAbsolute, join } from "node:path"
import { parseEnv } from "node:util"
import { readPrivateFile } from "../packages/opencode/src/quantcode/private-file"

const root = join(import.meta.dir, "..")
const mode = Bun.argv[2] ?? "web"
if (mode !== "web" && mode !== "desktop") {
  console.error(`Unknown QuantCode development mode: ${mode}`)
  process.exit(2)
}

// Host settings are data, never a shell script. Do not inherit model API keys,
// personal identity/group overrides or arbitrary process options from a file.
const hostKeys = new Set([
  "QUANTCODE_ROOT", "QUANTCODE_BACKEND_ROOT", "QUANTCODE_HOST_PYTHON",
  "QUANTCODE_PUBLIC_KEY_FILE", "QUANTCODE_PUBLIC_KEY_FILES", "QUANTCODE_IDENTITY_SESSION_FILE", "QUANTCODE_GATEWAY_URL",
  "QUANTCODE_ROSTER_FILE", "QUANTCODE_REMOTE_SSH_HOST", "QUANTCODE_GITHUB_CREDENTIALS_FILE",
  "QUANTCODE_GITHUB_SYNC_INTERVAL", "QUANTCODE_DREAM_INTERVAL", "QUANTCODE_DREAM_MIN_OCCURRENCES",
  "QUANTCODE_REQUIRE_INSTALLER", "QUANTCODE_BACKEND_PORT", "QUANTCODE_APP_PORT",
  "QUANTCODE_UNIFIED_RUNTIME", "QUANTCODE_TOKEN_BUDGET", "QUANTCODE_TOOL_CATALOG_FILE",
  "QUANTCODE_WORKSPACES_FILE", "QUANTCODE_SHARED_BLACKBOARD_DB", "QUANTCODE_SHARED_MEMORY",
  "QUANTCODE_DISTILL_CANDIDATES_DIR", "QUANTCODE_DISTILL_PUBLISH_ROOT",
  "QUANTCODE_LEGACY_CHECKPOINTS_DB", "QUANTCODE_LEGACY_PROVENANCE_FILE",
])
const configuredFile = process.env.QUANTCODE_HOST_ENV_FILE
const hostFile = configuredFile ?? join(root, "..", ".quantcode", "quantcode.local.env")
const hostEnv: Record<string, string> = {}
if (hostFile !== "") {
  if (!isAbsolute(hostFile)) {
    console.error("QUANTCODE_HOST_ENV_FILE 必须是绝对路径；空值表示不加载宿主配置。")
    process.exit(2)
  }
  let content: string | undefined
  let present = false
  try {
    const info = await lstat(hostFile)
    present = true
    if (info.isSymbolicLink() || !process.getuid) throw new Error("private host file cannot be verified")
    // Also checks current-user ownership, 0600-style permissions, no hard
    // links/symlinks and that the descriptor/path did not change during read.
    content = await readPrivateFile(hostFile, 262144)
  } catch (error) {
    if (present || configuredFile !== undefined || (error as NodeJS.ErrnoException).code !== "ENOENT") {
      console.error("无法加载 QuantCode 宿主配置：文件必须存在、归当前用户所有、仅当前用户可读写，且不能是符号链接。")
      process.exit(2)
    }
  }
  if (content !== undefined) {
    try {
      for (const [key, value] of Object.entries(parseEnv(content))) if (hostKeys.has(key)) hostEnv[key] = value
    } catch {
      console.error("QuantCode 宿主配置不是有效的环境变量文件；仅支持 KEY=value，不执行 shell 或变量展开。")
      process.exit(2)
    }
  }
}
const inherited = { ...hostEnv, ...process.env }
const backendRoot = inherited.QUANTCODE_ROOT ?? join(root, "..")
const pythonBin = join(backendRoot, ".venv", process.platform === "win32" ? "Scripts" : "bin")
const env: NodeJS.ProcessEnv = {
  ...inherited,
  OPENCODE_CHANNEL: "quantcode",
  QUANTCODE_ROOT: backendRoot,
  PATH: existsSync(pythonBin) ? `${pythonBin}${delimiter}${inherited.PATH ?? ""}` : inherited.PATH,
  QUANTCODE_BACKEND_ROOT: inherited.QUANTCODE_BACKEND_ROOT ?? join(root, ".."),
  MODELS_DEV_API_JSON:
    inherited.MODELS_DEV_API_JSON ?? join(root, "packages/opencode/test/tool/fixtures/models-api.json"),
}

const missingIdentity = ["QUANTCODE_PUBLIC_KEY_FILE", "QUANTCODE_IDENTITY_SESSION_FILE", "QUANTCODE_GATEWAY_URL"]
  .filter(key => !env[key]?.trim())
if (missingIdentity.length) console.warn(`QuantCode 身份配置缺失：${missingIdentity.join(", ")}。当前预览不能完成真实登录；请配置宿主连接后另行启动。`)
if (mode === "web" && (!env.QUANTCODE_HOST_PYTHON?.trim() || !env.QUANTCODE_BACKEND_ROOT?.trim())) {
  console.warn("QuantCode 网页预览的本机登录辅助需要 QUANTCODE_HOST_PYTHON 和 QUANTCODE_BACKEND_ROOT；桌面端通过本机 SSH agent 登录，不依赖此辅助。")
}
if (configuredFile === "") console.info("QuantCode 已按显式设置跳过宿主配置文件；仅继承本次进程环境。")

const backendPort = inherited.QUANTCODE_BACKEND_PORT ?? "4096"
const appPort = inherited.QUANTCODE_APP_PORT ?? "4444"

const commands =
  mode === "desktop"
    ? [["bun", "run", "--cwd", "packages/desktop", "dev"]]
    : [
        ["bun", "run", "--cwd", "packages/opencode", "--conditions=browser", "src/index.ts", "serve", "--port", backendPort],
        ["bun", "run", "--cwd", "packages/app", "dev", "--host", "127.0.0.1", "--port", appPort],
      ]

const processes = commands.map((command) =>
  Bun.spawn(command, {
    cwd: root,
    env: command.includes("packages/app")
      ? { ...env, VITE_OPENCODE_SERVER_HOST: "127.0.0.1", VITE_OPENCODE_SERVER_PORT: backendPort }
      : env,
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
