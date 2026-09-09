import type { OpencodeClient } from "@opencode-ai/sdk/v2/client"

/** Use only host-confirmed paths. A cached project is a preference, never a
 * filesystem grant; the login is pinned again immediately before selection. */
export async function prepareResearchWorkspace(client: OpencodeClient, input: {
  preferred?: string
  current: () => boolean
}) {
  const assertCurrent = () => {
    if (!input.current()) throw new Error("研究宿主已变化，请重新选择工作区。")
  }
  assertCurrent()
  const response = await client.quantcode.workspaces.list({ preferred: input.preferred }, { throwOnError: true })
  assertCurrent()
  if (!response.data) throw new Error("未取得当前身份的工作区，请重新登录。")
  const workspace = response.data
  if (!workspace.roots.length) throw new Error("当前宿主没有可用的研究工作区。请连接个人研究宿主，或请管理员登记工作区映射。")
  return {
    roots: workspace.roots,
    preferred: workspace.preferred,
    defaultDirectory: workspace.preferred ?? (workspace.roots.length === 1 ? workspace.roots[0].directory : undefined),
    async validate(directory: string) {
      assertCurrent()
      const result = await client.quantcode.workspaces.list({ preferred: directory,
        expected_session_id: workspace.login_session_id }, { throwOnError: true })
      assertCurrent()
      if (!result.data?.preferred || result.data.login_session_id !== workspace.login_session_id) {
        throw new Error("所选目录不再属于当前身份的授权工作区，请刷新后重试。")
      }
      return result.data.preferred
    },
  }
}
