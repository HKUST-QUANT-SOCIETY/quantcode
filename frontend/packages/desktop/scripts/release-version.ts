#!/usr/bin/env bun

const semver =
  /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$/

export function parseReleaseVersion(value: string) {
  const match = semver.exec(value)
  if (!match) return
  return {
    version: value,
    prerelease: match[4] !== undefined,
  }
}

if (import.meta.main) {
  const value = Bun.argv[2] ?? ""
  const parsed = parseReleaseVersion(value)
  if (!parsed) {
    console.error(`Invalid SemVer release version: ${value}`)
    process.exit(1)
  }

  console.log(`version=${parsed.version}`)
  console.log(`prerelease=${parsed.prerelease}`)
}
