import { $ } from "bun"

await $`bun ./scripts/copy-icons.ts ${process.env.OPENCODE_CHANNEL ?? "quantcode"}`

await $`cd ../opencode && bun script/build-node.ts`
