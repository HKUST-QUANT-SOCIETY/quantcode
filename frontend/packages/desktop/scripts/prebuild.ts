#!/usr/bin/env bun
import { $ } from "bun"

import { resolveChannel } from "./utils"

const channel = resolveChannel()
await $`bun ./scripts/copy-icons.ts ${channel}`
await $`bun ./scripts/copy-metainfo.ts ${channel}`

await $`bun script/build-node.ts`.cwd("../opencode").env({ ...process.env, OPENCODE_CHANNEL: channel })
