import { For, Show } from "solid-js"
import type { PermissionRequest } from "@opencode-ai/sdk/v2"
import { Button } from "@opencode-ai/ui/button"
import { DockPrompt } from "@opencode-ai/session-ui/dock-prompt"
import { Icon } from "@opencode-ai/ui/icon"
import { useLanguage } from "@/context/language"

export function SessionPermissionDock(props: {
  request: PermissionRequest
  responding: boolean
  onDecide: (response: "once" | "always" | "reject") => void
}) {
  const language = useLanguage()
  const exactGate = () => {
    const value = props.request.metadata.quantcodeExactGate
    if (!value || typeof value !== "object" || !("digest" in value) || typeof value.digest !== "string") return
    return { kind: "kind" in value && value.kind === "merge" ? "共享写入" : "受限资源访问",
      description: "description" in value && typeof value.description === "string" ? value.description : "",
      arguments: "arguments_json" in value && typeof value.arguments_json === "string" ? value.arguments_json : "" }
  }

  const toolDescription = () => {
    const key = `settings.permissions.tool.${props.request.permission}.description`
    const value = language.t(key as Parameters<typeof language.t>[0])
    if (value === key) return ""
    return value
  }

  return (
    <DockPrompt
      kind="permission"
      header={
        <div data-slot="permission-row" data-variant="header">
          <span data-slot="permission-icon">
            <Icon name="warning" size="normal" />
          </span>
          <div data-slot="permission-header-title">{exactGate() ? `确认${exactGate()!.kind}` : language.t("notification.permission.title")}</div>
        </div>
      }
      footer={
        <>
          <div />
          <div data-slot="permission-footer-actions">
            <Button variant="ghost" size="normal" onClick={() => props.onDecide("reject")} disabled={props.responding}>
              {language.t("ui.permission.deny")}
            </Button>
            <Show when={!exactGate()}><Button
              variant="secondary"
              size="normal"
              onClick={() => props.onDecide("always")}
              disabled={props.responding}
            >
              {language.t("ui.permission.allowAlways")}
            </Button></Show>
            <Button variant="primary" size="normal" onClick={() => props.onDecide("once")} disabled={props.responding}>
              {language.t("ui.permission.allowOnce")}
            </Button>
          </div>
        </>
      }
    >
      <Show when={toolDescription()}>
        <div data-slot="permission-row">
          <span data-slot="permission-spacer" aria-hidden="true" />
          <div data-slot="permission-hint">{toolDescription()}</div>
        </div>
      </Show>
      <Show when={exactGate()}>{gate => <div data-slot="permission-row">
        <span data-slot="permission-spacer" aria-hidden="true" />
        <div class="min-w-0 flex flex-col gap-2">
          <p class="text-12-regular text-text-base">此次确认只适用于下列操作与参数，需审批员或 Admin 确认；修改参数后需要重新申请。</p>
          <pre class="text-12-regular text-text-base whitespace-pre-wrap break-all max-h-60 overflow-auto">{gate().description}</pre>
          <pre class="text-12-regular text-text-base whitespace-pre-wrap break-all max-h-60 overflow-auto">{gate().arguments}</pre>
        </div>
      </div>}</Show>

      <Show when={props.request.patterns.length > 0}>
        <div data-slot="permission-row">
          <span data-slot="permission-spacer" aria-hidden="true" />
          <div data-slot="permission-patterns">
            <For each={props.request.patterns}>
              {(pattern) => <code class="text-12-regular text-text-base break-all">{pattern}</code>}
            </For>
          </div>
        </div>
      </Show>
    </DockPrompt>
  )
}
