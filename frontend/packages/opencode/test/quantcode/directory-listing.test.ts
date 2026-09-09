import { expect } from "bun:test"
import { Effect } from "effect"
import { LayerNode } from "@opencode-ai/core/effect/layer-node"
import { CrossSpawnSpawner } from "@opencode-ai/core/cross-spawn-spawner"
import { AppProcess } from "@opencode-ai/core/process"
import { which } from "@opencode-ai/core/util/which"
import { mkdir, writeFile, lstat, symlink, link } from "node:fs/promises"
import path from "node:path"
import { QuantCodeFileMutation } from "../../src/quantcode/file-mutation"
import { tmpdirScoped } from "../fixture/fixture"
import { testEffect } from "../lib/effect"

const it = testEffect(LayerNode.compile(LayerNode.group([AppProcess.node, CrossSpawnSpawner.node])))
const live = process.platform === "darwin" || process.platform === "linux" ? it.live : it.live.skip

live("native AppProcess lists a directory through the fixed helper with Node descriptor timestamps", () => Effect.gen(function* () {
  const temporary = yield* tmpdirScoped()
  const root = path.join(temporary, "research")
  yield* Effect.promise(async () => {
    await mkdir(root)
    await mkdir(path.join(root, "subproject"))
    await mkdir(path.join(root, ".quantcode"))
    await writeFile(path.join(root, "visible.txt"), "fixture")
    await writeFile(path.join(temporary, "outside.txt"), "fixture")
    await link(path.join(temporary, "outside.txt"), path.join(root, "hardlink.txt"))
    await symlink(path.join(root, "subproject"), path.join(root, "alias"))
  })
  const python = which("python3")
  if (!python) throw new Error("This regression requires the host's installed Python 3 runtime")
  const previous = { python: process.env.QUANTCODE_HOST_PYTHON, backend: process.env.QUANTCODE_BACKEND_ROOT }
  yield* Effect.addFinalizer(() => Effect.sync(() => {
    if (previous.python === undefined) delete process.env.QUANTCODE_HOST_PYTHON
    else process.env.QUANTCODE_HOST_PYTHON = previous.python
    if (previous.backend === undefined) delete process.env.QUANTCODE_BACKEND_ROOT
    else process.env.QUANTCODE_BACKEND_ROOT = previous.backend
  }))
  process.env.QUANTCODE_HOST_PYTHON = python
  process.env.QUANTCODE_BACKEND_ROOT = path.resolve(import.meta.dir, "../../../../..")
  const before = yield* Effect.promise(() => lstat(root, { bigint: true }))
  const processes = yield* AppProcess.Service
  const snapshot = { device: before.dev.toString(), inode: before.ino.toString(),
    modified: before.mtimeNs.toString(), changed: before.ctimeNs.toString() }
  const result = yield* QuantCodeFileMutation.runHost(processes, { version: 1, action: "list", root,
    relative: "", root_device: before.dev.toString(), root_inode: before.ino.toString(),
    denied: [".quantcode"], expected_directory: snapshot,
  }, undefined, 8 * 1024 * 1024)
  expect(result.exitCode).toBe(0)
  expect(result.stdoutTruncated).toBe(false)
  const output = JSON.parse(result.stdout.toString("utf8"))
  expect(output.ok).toBe(true)
  expect(output.directory).toEqual(snapshot)
  expect(output.entries.map((item: { name: string }) => item.name).sort()).toEqual(["subproject", "visible.txt"])
}))
