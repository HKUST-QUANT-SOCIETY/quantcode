import { describe, expect, test } from "bun:test"
import { fileURLToPath } from "node:url"

const root = fileURLToPath(new URL("../../..", import.meta.url))
const workflow = await Bun.file(`${root}/../.github/workflows/quantcode-desktop.yml`).text()
const action = await Bun.file(`${root}/.github/actions/build-quantcode-desktop/action.yml`).text()
const setupBun = await Bun.file(`${root}/.github/actions/setup-bun/action.yml`).text()
const packagedSmoke = await Bun.file(`${root}/packages/desktop/scripts/verify-packaged-launch.ts`).text()

describe("QuantCode desktop release workflow contract", () => {
  test("serializes and safely resumes publication by release tag", () => {
    expect(workflow).toContain("group: quantcode-release-${{ needs.version.outputs.tag }}")
    expect(workflow).toContain("already_published=true")
    expect(workflow).toContain("if: steps.stage.outputs.already_published != 'true'")
    expect(workflow).toContain('[[ "$draft" == "false" ]]')
  })

  test("supports signed artifact validation without forcing publication", () => {
    expect(workflow).toContain("sign:")
    expect(workflow).toContain("if: needs.version.outputs.sign == 'true'")
    expect(workflow).toContain("bun packages/desktop/scripts/release-plan.ts")
    expect(workflow).toContain("needs.version.outputs.publish == 'true'")
    expect(workflow).toContain("RELEASE_SIGNED: ${{ needs.version.outputs.sign }}")
    expect(workflow).toContain("PUBLISH_REQUESTED: ${{ needs.version.outputs.publish }}")
  })

  test("refuses to publish an unsigned or policy-mismatched release manifest", () => {
    expect(workflow).toContain("Verify approved release policy")
    expect(workflow).toContain('.schemaVersion == 2')
    expect(workflow).toContain('.distribution.releaseClass == "approved-release"')
    expect(workflow).toContain('.distribution.platformTrust.macos == "developer-id-notarized"')
    expect(workflow).toContain('.distribution.platformTrust.windows == "azure-trusted-signing"')
    expect(workflow).toContain('.distribution.platformTrust.linux == "approved-platform-unsigned"')
  })

  test("attests finalized installer provenance in the public source repository", () => {
    expect(workflow).toContain("attestations: write")
    expect(workflow).toContain("id-token: write")
    expect(workflow).toContain("actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6")
    expect(workflow).toContain("release-assets/*")
    expect(workflow).toContain("release-finalized/*")
  })

  test("runs package-level smoke and content checks on every platform", () => {
    expect(action).toContain("hdiutil attach -nobrowse -readonly")
    expect(action).toContain('Start-Process -FilePath $installer.FullName -ArgumentList @("/S", "/D=$installRoot")')
    expect(action).toContain("--appimage-extract")
    expect(action).toContain("dpkg-deb --contents")
    expect(action).toContain("rpm -qlp")
    expect(action).toContain('if ($LASTEXITCODE -ne 0) { throw "QuantCode packaged launch smoke failed with exit code $LASTEXITCODE" }')
    expect(action).toContain('dpkg-deb --fsys-tarfile "$deb" | tar -xOf -')
    expect(action).not.toContain('dpkg-deb --fsys-tarfile "$deb" | tar -xOJf -')
  })

  test("packaging removes empty signing inputs but preserves nonempty signed credentials", async () => {
    const parsed = Bun.YAML.parse(action) as { runs: { steps: Array<{ name?: string; run?: string }> } }
    const packaging = parsed.runs.steps.find(step => step.name === "Package installers")!.run!
    const cleanup = packaging.slice(0, packaging.indexOf("read -r -a platform_args"))
    for (const value of ["", "fixture-certificate"]) {
      const child = Bun.spawn(["bash", "-euc", cleanup + `\n[[ \${CSC_LINK+x} == '${value ? "x" : ""}' ]]\n[[ \${APPLE_API_KEY:-} == fixture-key ]]\n[[ \${CSC_IDENTITY_AUTO_DISCOVERY} == false ]]`], {
        env: { ...process.env, CSC_LINK: value, CSC_KEY_PASSWORD: "", APPLE_API_KEY: "fixture-key", APPLE_API_KEY_ID: "",
          APPLE_API_ISSUER: "", AZURE_CLIENT_ID: "", AZURE_TENANT_ID: "", AZURE_SUBSCRIPTION_ID: "",
          AZURE_TRUSTED_SIGNING_ACCOUNT_NAME: "", AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE: "",
          AZURE_TRUSTED_SIGNING_ENDPOINT: "", AZURE_TRUSTED_SIGNING_PUBLISHER_NAME: "", CSC_IDENTITY_AUTO_DISCOVERY: "false" },
        stdout: "pipe", stderr: "pipe",
      })
      const [code, error] = await Promise.all([child.exited, new Response(child.stderr).text()])
      expect(code, error).toBe(0)
    }
  })

  test("fails packaged smoke when the QuantCode research workspace is missing", () => {
    expect(packagedSmoke).toContain('[data-quantcode-workspace="true"]')
    expect(packagedSmoke).toContain("renderer did not mount the QuantCode research workspace")
  })

  test("dispatches the actual root workflow with a distinct internal test publication policy", () => {
    expect(workflow).toContain("workflow_dispatch:")
    expect(workflow).toContain("internal_test:")
    expect(workflow).toContain("matrix: ${{ fromJSON(needs.version.outputs.unsigned_matrix) }}")
    expect(workflow).toContain("Verify internal test policy")
    expect(workflow).toContain('.distribution.releaseClass == "internal-test"')
    expect(workflow).toContain('.release.prerelease == true')
    expect(workflow).toContain("quantcode-test-publish")
    expect(workflow).toContain("flags+=(--prerelease --latest=false)")
    expect(workflow).toContain('git rev-parse "$tag^{commit}"')
    expect(workflow).toContain('gh api "repos/$TARGET_REPOSITORY/git/refs" -f "ref=$ref" -f "sha=$GITHUB_SHA"')
    expect(workflow).toContain('gh api "repos/$TARGET_REPOSITORY/git/ref/tags/$TAG" --jq .object.sha')
    expect(workflow).not.toContain('git/ref/$ref')
    expect(workflow).toContain('gh release view "$TAG" --repo "$TARGET_REPOSITORY" --json assets')
    expect(workflow).not.toContain('gh api "repos/$TARGET_REPOSITORY/releases/tags/$TAG"')
  })

  test("uses the native Node 24 checkout action for every release job", () => {
    const checkout = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1"
    expect(workflow.match(new RegExp(checkout.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g"))).toHaveLength(7)
    expect(workflow).not.toContain("# v3.6.0")
  })

  test("uses Node 24 artifact and signing action revisions", () => {
    expect(workflow).toContain("actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1")
    expect(workflow).toContain("actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1")
    expect(workflow).toContain("actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6 # v4.2.2")
    expect(action).toContain("actions/setup-node@820762786026740c76f36085b0efc47a31fe5020 # v7.0.0")
    expect(action).toContain("azure/login@7ddb5af1ef8758cf1353cf3b42f940aee27ba21c # v3.0.2")
    expect(setupBun).toContain("actions/cache/restore@55cc8345863c7cc4c66a329aec7e433d2d1c52a9 # v6.1.0")
    expect(setupBun).toContain("actions/cache/save@55cc8345863c7cc4c66a329aec7e433d2d1c52a9 # v6.1.0")
  })
})
