import { parseReleaseVersion } from "./release-version"

export const internalTestTargets = ["x86_64-apple-darwin", "aarch64-apple-darwin", "x86_64-pc-windows-msvc"]
const targets = [
  { name: "macOS Intel", runner: "macos-15-intel", target: internalTestTargets[0], platform: "--mac --x64", install: "--os=darwin --cpu=x64" },
  { name: "macOS Apple Silicon", runner: "macos-15", target: internalTestTargets[1], platform: "--mac --arm64", install: "--os=darwin --cpu=arm64" },
  { name: "Windows x64", runner: "windows-2025", target: internalTestTargets[2], platform: "--win --x64", install: "--os=win32 --cpu=x64" },
  { name: "Linux x64", runner: "ubuntu-24.04", target: "x86_64-unknown-linux-gnu", platform: "--linux --x64", install: "--os=linux --cpu=x64" },
]

export const isInternalTestVersion = (version: string) => !!parseReleaseVersion(version) && /^\d+\.\d+\.\d+-test\.\d+$/.test(version)

export function releasePlan(input: {
  version?: string
  publish: boolean
  sign: boolean
  internalTest: boolean
  refType: string
  refName: string
  defaultBranch: string
  runNumber: string
}) {
  const prefix = "quantcode-v"
  if (input.refType === "tag" && !input.refName.startsWith(prefix)) throw new Error(`Expected a ${prefix} release tag`)
  const version = input.refType === "tag" ? input.refName.slice(prefix.length)
    : input.version || (input.internalTest ? "1.0.0-test.1" : `0.1.${input.runNumber}`)
  const parsed = parseReleaseVersion(version)
  if (!parsed) throw new Error(`Invalid SemVer release version: ${version}`)
  if (input.refType === "tag" && input.version && input.version !== version) throw new Error("Requested version must match the source tag")
  if (input.internalTest && !isInternalTestVersion(version)) throw new Error("Internal tests require an X.Y.Z-test.N version")
  if (input.internalTest && input.sign) throw new Error("Internal-test packages are unsigned; use the approved signing path for signed releases")
  const sign = !input.internalTest && (input.sign || input.publish)
  if ((sign || input.publish) && input.refType !== "tag" && input.refName !== input.defaultBranch) {
    throw new Error("Publishing and signed builds require the default branch or a verified release tag")
  }
  const active = input.internalTest ? targets.filter(item => internalTestTargets.includes(item.target)) : targets
  return {
    version, tag: `${prefix}${version}`, publish: input.publish, sign,
    internal_test: input.internalTest, prerelease: parsed.prerelease,
    title: input.internalTest ? `QuantCode Test V${version.split(".").slice(0, 2).join(".")} (${version})` : `QuantCode ${version}`,
    required_targets: active.map(item => item.target).join(","),
    unsigned_matrix: JSON.stringify({ include: active }),
  }
}

if (import.meta.main) {
  const flag = (name: string) => {
    const value = process.env[name] ?? "false"
    if (!["", "true", "false"].includes(value)) throw new Error(`${name} must be true or false`)
    return value === "true"
  }
  const plan = releasePlan({ version: process.env.INPUT_VERSION, publish: flag("INPUT_PUBLISH"), sign: flag("INPUT_SIGN"),
    internalTest: flag("INPUT_INTERNAL_TEST"), refType: process.env.GITHUB_REF_TYPE ?? "branch", refName: process.env.GITHUB_REF_NAME ?? "",
    defaultBranch: process.env.DEFAULT_BRANCH ?? "main", runNumber: process.env.GITHUB_RUN_NUMBER ?? "0" })
  for (const [name, value] of Object.entries(plan)) console.log(`${name}=${value}`)
}
