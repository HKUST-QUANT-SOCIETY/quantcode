import type { OpencodeClient } from "@opencode-ai/sdk/v2/client"

/** Unknown capabilities cannot enable legacy workspace mutations. */
export async function projectRuntime(client: OpencodeClient): Promise<"native" | "legacy"> {
  const result = await client.experimental.capabilities.get(undefined, { throwOnError: true })
  const native = result.data?.quantcodeUnifiedRuntime
  if (typeof native !== "boolean") throw new Error("无法确认研究宿主的运行模式，请检查连接后重试。")
  return native ? "native" : "legacy"
}

export async function saveProjectAppearance(client: OpencodeClient, input: {
  projectID: string; directory: string; name: string; icon: { color: string; override: string }; start: string;
}, mode: "native" | "legacy") {
  return client.project.update({ projectID: input.projectID, directory: input.directory, name: input.name, icon: input.icon,
    ...(mode === "legacy" ? { commands: { start: input.start } } : {}),
  }, { throwOnError: true })
}
