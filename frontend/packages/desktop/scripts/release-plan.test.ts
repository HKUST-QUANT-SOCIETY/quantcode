import { expect, test } from "bun:test"
import { internalTestTargets, releasePlan } from "./release-plan"

const input = { publish: false, sign: false, internalTest: false, refType: "branch", refName: "main", defaultBranch: "main", runNumber: "12" }

test("internal Test V1.0 publishes only unsigned Mac and Windows prerelease targets", () => {
  const plan = releasePlan({ ...input, publish: true, internalTest: true })
  expect(plan).toMatchObject({ version: "1.0.0-test.1", tag: "quantcode-v1.0.0-test.1", sign: false, publish: true,
    internal_test: true, prerelease: true, title: "QuantCode Test V1.0 (1.0.0-test.1)" })
  expect(plan.required_targets.split(",")).toEqual(internalTestTargets)
  expect(JSON.parse(plan.unsigned_matrix).include.map((item: { target: string }) => item.target)).toEqual(internalTestTargets)
})

test("formal publication still forces the protected signed path and includes Linux", () => {
  const plan = releasePlan({ ...input, version: "1.0.0", publish: true })
  expect(plan).toMatchObject({ tag: "quantcode-v1.0.0", sign: true, internal_test: false, prerelease: false })
  expect(plan.required_targets).toContain("x86_64-unknown-linux-gnu")
})

test.each(["1.0.0", "1.0.0-rc.1", "1.0.0-test.01", "1.0.0-test.1+unverified"])("rejects invalid internal-test version %s", version => {
  expect(() => releasePlan({ ...input, internalTest: true, version })).toThrow()
})

test("internal mode cannot claim signed trust or publish from an arbitrary branch", () => {
  expect(() => releasePlan({ ...input, internalTest: true, sign: true })).toThrow("unsigned")
  expect(() => releasePlan({ ...input, internalTest: true, publish: true, refName: "unreviewed" })).toThrow("default branch")
  expect(releasePlan({ ...input, internalTest: true, refName: "unreviewed" }).publish).toBe(false)
})

test("tag dispatch must match the requested version and distribution", () => {
  expect(releasePlan({ ...input, internalTest: true, refType: "tag", refName: "quantcode-v1.0.0-test.1" }).tag).toBe("quantcode-v1.0.0-test.1")
  expect(() => releasePlan({ ...input, internalTest: true, refType: "tag", refName: "quantcode-v1.0.0-test.1", version: "1.0.0-test.2" })).toThrow("match")
  expect(() => releasePlan({ ...input, refType: "tag", refName: "v1.0.0-test.1" })).toThrow("quantcode-v")
})
