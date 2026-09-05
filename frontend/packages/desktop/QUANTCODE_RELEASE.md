# QuantCode desktop release

Member-facing install and manual-upgrade steps are documented in
[`QUANTCODE_INSTALL.md`](./QUANTCODE_INSTALL.md).

The `QuantCode desktop installers` workflow currently produces these supported
release targets:

- macOS Intel: DMG and ZIP
- macOS Apple Silicon: DMG and ZIP
- Windows x64: NSIS installer
- Linux x64: AppImage, DEB, and RPM

The active workflow validates four platform/architecture targets. Linux arm64
support remains available in the build action and metadata finalizer, but it is
not part of the active matrix or published asset set.

The desktop source lives in the `HKUST-QUANT-SOCIETY/opencode` fork, while
release assets target `HKUST-QUANT-SOCIETY/quantcode`. The workflow must be
merged into the source repository's default `dev` branch before
`workflow_dispatch` is available. A pull request runs unsigned packaging and
the packaged-launch smoke test; a tag named `quantcode-vX.Y.Z`, or a manual
dispatch from `dev` with `publish=true`, runs the approved release path.
Manual dispatch also accepts `sign=true,publish=false`: this runs the protected
Apple, Azure, and Linux release jobs, finalizes and attests their artifacts, but
does not mutate the target GitHub Release. Use that mode to validate signing
and notarization before the first production publication.

The target repository is currently private. Browser or GitHub CLI login is not
inherited by an installed Electron app, so an anonymous `electron-updater`
GitHub feed cannot read its releases. Every current QuantCode CI build sets
`QUANTCODE_UPDATE_FEED=disabled`; signing an installer does not turn on an
unreachable updater. Users can install and run these packages normally, but
updates are manual until either the release repository/assets are public or a
controlled update service/user-authenticated token flow is implemented. Never
embed a long-lived repository PAT in the desktop bundle.

The build embeds the tracked
`packages/opencode/test/tool/fixtures/models-api.json` snapshot through
`MODELS_DEV_API_JSON`. This keeps all four active targets reproducible when
`models.dev` is unavailable. Refresh that snapshot deliberately when the
supported provider catalog changes, review the diff, and commit it with the
release workflow change.

## Release signing

The `signing_mode=unsigned` profile is used only for pull-request and
artifact-only QA runs. Linux release assets are platform-unsigned by design,
but use the separate `signing_mode=none` profile behind release approval.
Publishing fails closed unless every protected release job succeeds and all
required macOS, Windows, and publishing credentials are present. Protect these
GitHub environments with required reviewers before enabling `publish`:

- `quantcode-release-macos`: Apple signing and notarization secrets only.
- `quantcode-release-windows`: Azure Trusted Signing secrets only, plus OIDC
  approval for the Windows job.
- `quantcode-release-linux`: approval only; it contains no platform signing or
  publishing secret.
- `quantcode-release-publish`: `QUANTCODE_RELEASE_TOKEN` only, for the release
  repository upload and final publication.

### Provisioning checklist

Provision these materials directly in the named GitHub Environment. Do not put
a certificate, API key, private key, or release token in a pull request, issue,
chat message, workflow input, or local configuration committed to the repo.

1. **Apple Developer ID and notarization**: create a Developer ID Application
   certificate for `org.hkust.quantcode`, export its `.p12`, and create an App
   Store Connect API key authorized for notarization. Base64-encode the `.p12`
   only for the `APPLE_CERTIFICATE` environment secret. Store the `.p12`
   password and `.p8` contents in their separate secrets.
2. **Azure Trusted Signing**: create an Entra application and a federated
   credential constrained to
   `repo:HKUST-QUANT-SOCIETY/opencode:environment:quantcode-release-windows`.
   Grant it only the Azure Trusted Signing permissions required by the selected
   account and certificate profile. Record the exact certificate Subject DN in
   `AZURE_TRUSTED_SIGNING_PUBLISHER_NAME`; the workflow rejects a different
   signer on either `QuantCode.exe` or the NSIS installer.
3. **Private release publisher**: create a short-lived fine-grained token for
   `HKUST-QUANT-SOCIETY/quantcode` with only Contents read/write permission.
   Store it as `QUANTCODE_RELEASE_TOKEN` in `quantcode-release-publish`, not
   at repository or organization scope. The build jobs never receive it.
4. **Approval path**: keep `dev` and `quantcode-v*` as the only deployment
   sources for every release environment, and approve the macOS, Windows,
   Linux, and publish environments separately for a signed run.

After provisioning, first dispatch `sign=true,publish=false` from `dev` and
verify the signed macOS/Windows jobs, Apple stapling, Azure signature Subject
DN, schema-v2 `approved-release` manifest, and provenance. Only then dispatch
or tag a run with `publish=true`.

### macOS

The two macOS jobs use these `quantcode-release-macos` environment secrets:

- `APPLE_CERTIFICATE`: base64-encoded Developer ID Application `.p12`
- `APPLE_CERTIFICATE_PASSWORD`
- `APPLE_API_KEY_CONTENT`: contents of the App Store Connect `.p8` key
- `APPLE_API_KEY_ID`
- `APPLE_API_ISSUER`

The workflow imports the certificate, signs with hardened runtime, notarizes,
and verifies `codesign`, Gatekeeper assessment, and the stapled notarization
ticket before uploading the artifacts.

### Windows

The Windows job uses these `quantcode-release-windows` environment secrets:

- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`
- `AZURE_TRUSTED_SIGNING_ACCOUNT_NAME`
- `AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE`
- `AZURE_TRUSTED_SIGNING_ENDPOINT`
- `AZURE_TRUSTED_SIGNING_PUBLISHER_NAME`

`AZURE_TRUSTED_SIGNING_PUBLISHER_NAME` must be the complete certificate
Subject DN returned by
`(Get-AuthenticodeSignature .\\QuantCode.exe).SignerCertificate.Subject`.
The workflow authenticates to Azure Trusted Signing with `id-token: write`,
signs the NSIS executable with SHA-256, and verifies the installer and unpacked
application signatures. The macOS jobs do not receive Azure credentials or
OIDC write permission.

### Linux

The Linux x64 job uses the protected `quantcode-release-linux` environment, but
it receives no Apple, Azure, or GitHub release credential. Linux has no platform
code-signing provider in this workflow, and electron-builder SHA-512 metadata
is an integrity check rather than an independent signature. Linux packages are
therefore built with `signing_mode=none` and updater trust disabled; they do not
claim an ELF, AppImage, DEB, RPM, or updater-metadata signature.

Only the AppImage is represented in `latest-linux.yml`; DEB and RPM remain
manual installation assets. Linux automatic updates must remain disabled until
the client verifies signed metadata or an equivalent independent trust anchor.
The current private release feed is disabled for Linux just as it is for macOS
and Windows.

QuantCode stores updater downloads under `quantcode-updater` and uses a
separate `quantcode.updater` preference store, so an OpenCode installation
cannot reuse or overwrite its update state. Signed macOS/Windows builds verify
their platform signatures and disallow downgrade; Linux update metadata is
generated for release consistency only. The updater is enabled only when
`QUANTCODE_UPDATE_MODE=signed` and `QUANTCODE_UPDATE_FEED=public`; the current
private-repository release therefore remains disabled. Unsigned mode is only
for local or artifact-only testing and must never be published.

### GitHub release publishing

The `quantcode-release-publish` environment contains `QUANTCODE_RELEASE_TOKEN`.
It is used only by the final release job to upload verified artifacts to the
private `HKUST-QUANT-SOCIETY/quantcode` repository. It is never passed to the
desktop build and is never embedded in an installer.

QuantCode currently disables automatic installation of the upstream OpenCode
CLI inside WSL. Re-enable that control only after a versioned
QuantCode-compatible WSL backend is published.

## Release process

`Finalize release bundle` runs after either the unsigned PR matrix or all four
release targets. It validates the exact active installer set, verifies updater
metadata against local file names, sizes, and SHA-512 values, merges the two
macOS feeds, and writes:

- `latest-mac.yml` (both macOS architectures)
- `latest.yml` (Windows x64)
- `latest-linux.yml` (Linux x64 AppImage only)
- `release-manifest.json` (schema v2 source, release, per-platform trust policy, sizes, and SHA-256)
- `SHA256SUMS` (packages and generated metadata)

The public source repository then uses GitHub OIDC and `actions/attest` to
create Sigstore-backed build provenance for every installer and finalized
metadata file. This trust record is separate from the cross-repository release
token, so replacing a Linux package and its checksum in the private release
repository does not produce matching source-repository provenance. Verify a
download with:

```bash
gh attestation verify <installer> -R HKUST-QUANT-SOCIETY/opencode
```

For a published run, a separate release job creates or reuses a draft release,
uploads only the finalized assets, compares remote names, sizes, and GitHub
SHA-256 digests, and publishes only after verification. It refuses to replace
an already published release.

## Packaged launch smoke test

Each active target exercises the installable package after electron-builder:
macOS mounts the DMG and launches its app after checking the ZIP archive;
Windows silently installs the NSIS package into a temporary location, launches
it, and runs its uninstaller; Linux extracts and launches the AppImage while
also validating the DEB/RPM launcher, executable, icon, and AppStream paths.
The test sets `OPENCODE_TEST_ONBOARDING=1` and passes
Chromium's remote debugging address and a newly allocated loopback port as
command-line arguments. `packages/desktop/scripts/verify-packaged-launch.ts`
then polls `/json/list` with bounded timeouts and verifies:

- an Electron `oc://renderer/` page titled `QuantCode`;
- `document.readyState === "complete"` and a mounted `#root`;
- the stable `data-product="quantcode"` renderer marker;
- at least one interactive control and a healthy local sidecar;
- a two-second stable state before passing.

The smoke process receives its PID so cleanup can terminate the complete
process tree (`kill` on macOS/Linux and `taskkill /T /F` on Windows). Linux runs
the unpacked app under `xvfb-run`; the release action installs Xvfb and the DEB
and RPM packaging tools on the Ubuntu runner. Before launch, CI restores the
unpacked Chromium `chrome-sandbox` helper to `root:root` mode `4755`, matching a
system installation instead of disabling Chromium's sandbox. The packaged
assets are not rewritten by this smoke-only preparation. The debug port is
loopback-only, random per run, and never enabled by a normal packaged launch.
There is no `QUANTCODE_PACKAGED_SMOKE` product flag.

Run an artifact-only build from the default branch with:

```bash
gh workflow run quantcode-desktop.yml -R HKUST-QUANT-SOCIETY/opencode -f version=0.1.0 -f sign=false -f publish=false
```

Run a protected signed, non-publishing validation with:

```bash
gh workflow run quantcode-desktop.yml -R HKUST-QUANT-SOCIETY/opencode -f version=0.1.0 -f sign=true -f publish=false
```

For pull requests, inspect `Finalize release bundle` and its
`release-metadata` artifact in addition to the four target jobs. A green
packaging job without finalization is not release evidence.

Before a publish, verify every environment approval and required secret above.
After download, verify the checksum manifest on macOS with
`shasum -a 256 -c SHA256SUMS`, on Linux with
`sha256sum -c SHA256SUMS`, and on Windows with
`Get-FileHash -Algorithm SHA256` compared with `SHA256SUMS`.

## Local macOS package

From `packages/desktop`:

```bash
OPENCODE_CHANNEL=quantcode QUANTCODE_UNSIGNED_BUILD=true MODELS_DEV_API_JSON=../opencode/test/tool/fixtures/models-api.json bun run build
OPENCODE_CHANNEL=quantcode QUANTCODE_UNSIGNED_BUILD=true MODELS_DEV_API_JSON=../opencode/test/tool/fixtures/models-api.json CSC_IDENTITY_AUTO_DISCOVERY=false bunx electron-builder --mac --publish never --config electron-builder.config.ts
```

The unsigned package is for QA only and may show macOS trust warnings. A
production package requires the Apple signing and notarization secrets in CI.
Automatic updates remain disabled unless the package is signed and
`QUANTCODE_UPDATE_FEED=public` is deliberately enabled for a public or
authenticated feed.

## Local Windows package

From `packages/desktop` on Windows PowerShell:

```powershell
$env:OPENCODE_CHANNEL = "quantcode"
$env:QUANTCODE_UNSIGNED_BUILD = "true"
$env:MODELS_DEV_API_JSON = "../opencode/test/tool/fixtures/models-api.json"
$env:QUANTCODE_UPDATE_FEED = "disabled"
bun run build
bun run package:win
```

The installer is written to `dist/quantcode-<version>-win-x64.exe`; the
unpacked application used by CI is under `dist/*-unpacked/QuantCode.exe`. A
local unsigned package is for QA only and may trigger SmartScreen.

## Local Linux package

From `packages/desktop` on x64 Linux:

```bash
export OPENCODE_CHANNEL=quantcode
export QUANTCODE_UNSIGNED_BUILD=true
export QUANTCODE_UPDATE_FEED=disabled
export MODELS_DEV_API_JSON=../opencode/test/tool/fixtures/models-api.json
bun run build
bun run package:linux
```

The outputs are `dist/quantcode-<version>-linux-x86_64.AppImage`,
`dist/quantcode-<version>-linux-amd64.deb`, and
`dist/quantcode-<version>-linux-x86_64.rpm`. The unpacked application used by
CI is `dist/linux-unpacked/quantcode`. Run it in a graphical session or under
`xvfb-run` for headless smoke testing. Local outputs are unsigned QA packages;
the protected Linux CI job is the source of publishable release assets.
