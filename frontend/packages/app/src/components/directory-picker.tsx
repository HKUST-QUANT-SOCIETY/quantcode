import { useDialog } from "@opencode-ai/ui/context/dialog"
import { ServerConnection, useServer } from "@/context/server"
import { usePlatform } from "@/context/platform"
import { useSettings } from "@/context/settings"
import { createEffect, lazy, on, onCleanup } from "solid-js"
import { useGlobal } from "@/context/global"
import { isQuantCode } from "@/brand"
import { showToast } from "@/utils/toast"
import { errorMessage } from "@/pages/layout/helpers"
import { DialogSelectDirectory } from "./dialog-select-directory"
import { directoryPickerKind } from "./directory-picker-policy"
import { openNativeDirectoryPicker } from "./directory-picker-native"
import { prepareResearchWorkspace } from "./quantcode/workspaces"

const DialogSelectDirectoryV2 = lazy(() =>
  import("./dialog-select-directory-v2").then((module) => ({ default: module.DialogSelectDirectoryV2 })),
)

type DirectoryPickerInput = {
  server: ServerConnection.Any
  title?: string
  multiple?: boolean
  preferred?: string
  /** New-task entry may use a validated recent project or the only root. */
  useDefault?: boolean
  onSelect: (result: string | string[] | null) => void
}

export function useDirectoryPicker() {
  const platform = usePlatform()
  const settings = useSettings()
  const dialog = useDialog()
  const global = useGlobal()
  const server = useServer()
  let generation = 0
  let activeCancel: (() => void) | undefined
  let activeClose: (() => void) | undefined
  const cancelPending = () => {
    generation += 1
    const cancel = activeCancel
    const close = activeClose
    activeCancel = undefined
    activeClose = undefined
    cancel?.()
    close?.()
  }
  createEffect(on(() => [server.key, JSON.stringify(server.list)], cancelPending, { defer: true }))
  onCleanup(cancelPending)

  return (input: DirectoryPickerInput) => {
    cancelPending()
    const request = ++generation
    const activeServer = server.key
    const connection = JSON.stringify(input.server)
    const current = () => generation === request && server.key === activeServer &&
      server.list.some(item => ServerConnection.key(item) === ServerConnection.key(input.server) && JSON.stringify(item) === connection)
    let delivered = false
    const deliver = (result: string | string[] | null) => {
      if (delivered) return
      delivered = true
      input.onSelect(result)
      if (generation === request) activeCancel = undefined
    }
    activeCancel = () => deliver(null)
    const select = (result: string | string[] | null) => deliver(current() ? result : null)
    const showLegacy = () => {
      if (input.useDefault && input.preferred) {
        select(input.preferred)
        return
      }
      if (directoryPickerKind(platform.platform, input.server) === "native" && platform.platform === "desktop") {
        void openNativeDirectoryPicker(
          () => platform.openDirectoryPickerDialog({ title: input.title, multiple: input.multiple }), select,
        )
        return
      }

      let selected = false
      const onSelect = (result: string | string[] | null) => {
        selected = result !== null
        select(result)
      }
      const cancel = () => {
        if (!selected) select(null)
        if (generation === request) activeClose = undefined
      }
      if (platform.platform === "desktop" && settings.general.newLayoutDesigns()) {
        dialog.show(() => <DialogSelectDirectoryV2 {...input} onSelect={onSelect} />, cancel)
        activeClose = () => dialog.close()
        return
      }
      dialog.show(() => <DialogSelectDirectory {...input} onSelect={onSelect} />, cancel)
      activeClose = () => dialog.close()
    }
    if (!isQuantCode) return showLegacy()
    const client = global.ensureServerCtx(input.server).sdk.client
    void (async () => {
      const capabilities = await client.experimental.capabilities.get()
      if (!current()) return deliver(null)
      if (capabilities.error || !capabilities.data) throw new Error("无法确认研究宿主的运行模式，请检查连接。")
      if (capabilities.data.quantcodeUnifiedRuntime !== true) return showLegacy()
      const workspace = await prepareResearchWorkspace(client, { preferred: input.preferred, current })
      const directory = workspace.defaultDirectory
      if (input.useDefault && directory) {
        select(await workspace.validate(directory))
        return
      }
      dialog.show(() => <DialogSelectDirectoryV2 {...input} start={directory} authorizedRoots={workspace.roots}
        validateSelection={workspace.validate} onSelect={select} />, () => {
          deliver(null)
          if (generation === request) activeClose = undefined
        })
      activeClose = () => dialog.close()
    })().catch(error => {
      if (current()) showToast({ variant: "error", title: "无法打开研究工作区", description: errorMessage(error, "研究工作区暂不可用，请重试。") })
      deliver(null)
    })
  }
}
