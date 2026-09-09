import { Show, type JSX } from "solid-js"
import { WordmarkV2 } from "@opencode-ai/ui/v2/wordmark-v2"
import { NEW_SESSION_CONTENT_WIDTH } from "@/pages/session/new-session-layout"
import { isQuantCode, PRODUCT_NAME } from "@/brand"

export function NewSessionDesignView(props: { children: JSX.Element }) {
  return (
    <div data-component="session-new-design" class="relative size-full overflow-hidden bg-v2-background-bg-deep ">
      <div class="absolute inset-x-0 top-[25.375%] flex justify-center px-6">
        <div class={NEW_SESSION_CONTENT_WIDTH}>
          <Show when={isQuantCode} fallback={<WordmarkV2 class="h-auto w-full text-v2-icon-icon-base" />}>
            <div class="flex items-center gap-3 text-v2-text-text-base">
              <span aria-hidden="true" class="flex size-10 items-center justify-center rounded-lg bg-v2-background-bg-layer-03 text-sm font-semibold">QC</span>
              <div><div class="text-xs text-v2-text-text-muted">{PRODUCT_NAME}</div><h1 class="text-[24px] leading-[1.3] font-semibold">新建研究任务</h1></div>
            </div>
          </Show>
          <div class="mt-8">{props.children}</div>
        </div>
      </div>
    </div>
  )
}
