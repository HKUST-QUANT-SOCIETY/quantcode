import { expect, test } from "bun:test"
import { parseReleaseVersion } from "./release-version"

test.each(["0.1.0", "1.17.11", "2.0.0-alpha.1", "3.4.5-rc.2+build.9"])("accepts SemVer %s", (version) => {
  expect(parseReleaseVersion(version)).toEqual({
    version,
    prerelease: version.includes("-"),
  })
})

test.each(["", "v1.2.3", "01.2.3", "1.02.3", "1.2", "1.2.3.foo", "1.2.3-alpha..1", "1.2.3-01"])(
  "rejects invalid release version %s",
  (version) => {
    expect(parseReleaseVersion(version)).toBeUndefined()
  },
)
