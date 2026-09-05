# Install QuantCode Desktop

QuantCode Desktop is distributed to authorized HKUST Quant Society members
through the private `HKUST-QUANT-SOCIETY/quantcode` GitHub Releases page. A
workflow artifact from a pull request is an unsigned QA build, not a formal
release. Install a team release only when its `release-manifest.json` has
`distribution.releaseClass` set to `approved-release`.

## Choose a package

| Platform | Package |
| --- | --- |
| macOS Apple Silicon | `quantcode-<version>-mac-arm64.dmg` |
| macOS Intel | `quantcode-<version>-mac-x64.dmg` |
| Windows x64 | `quantcode-<version>-win-x64.exe` |
| Linux x64, portable | `quantcode-<version>-linux-x86_64.AppImage` |
| Ubuntu/Debian x64 | `quantcode-<version>-linux-amd64.deb` |
| Fedora/RHEL x64 | `quantcode-<version>-linux-x86_64.rpm` |

Download the package, `release-manifest.json`, and `SHA256SUMS` from the same
release. GitHub authentication is required because the release repository is
private.

## Verify the download

Every formal bundle records the exact source commit, workflow run, package
size, SHA-256 digest, and platform trust policy. Compare the package digest
with `SHA256SUMS` before opening it:

```bash
# macOS
shasum -a 256 ./quantcode-0.1.0-mac-arm64.dmg

# Linux
sha256sum ./quantcode-0.1.0-linux-x86_64.AppImage
```

On Windows PowerShell:

```powershell
Get-FileHash -Algorithm SHA256 .\quantcode-0.1.0-win-x64.exe
```

Compare the printed value with the matching `SHA256SUMS` line. With GitHub CLI
installed, verify source-workflow provenance as well:

```bash
gh attestation verify ./quantcode-0.1.0-mac-arm64.dmg -R HKUST-QUANT-SOCIETY/opencode
```

The macOS manifest must report `developer-id-notarized`; the Windows manifest
must report `azure-trusted-signing`. Linux is intentionally reported as
`approved-platform-unsigned`: verify both SHA-256 and GitHub provenance before
installing it.

## Install

### macOS

Open the DMG, drag **QuantCode** to **Applications**, then launch QuantCode from
Applications. The formal package is signed with Developer ID and notarized by
Apple. Do not bypass Gatekeeper for an unsigned pull-request artifact.

### Windows

Run the x64 installer. QuantCode is installed for the current user and appears
in the Start menu. The formal installer and `QuantCode.exe` are signed with the
publisher recorded in the release manifest.

### Linux

For AppImage:

```bash
chmod +x quantcode-0.1.0-linux-x86_64.AppImage
./quantcode-0.1.0-linux-x86_64.AppImage
```

For Debian/Ubuntu:

```bash
sudo apt install ./quantcode-0.1.0-linux-amd64.deb
```

For Fedora/RHEL:

```bash
sudo dnf install ./quantcode-0.1.0-linux-x86_64.rpm
```

## Connect your workspace

Installers do not contain a GitHub PAT, an SSH private key, or a QuantCode
Python checkout. Configure the Server B connection with the member credentials
issued to you, then enable the required QuantCode MCP server for your group.
Keep private keys in the operating-system credential or SSH store, never in a
project file or the desktop package.

## Upgrade

Automatic updates are disabled while releases remain private. To upgrade:

1. Quit QuantCode completely.
2. Download and verify the newer package for the same architecture.
3. Install it over the existing application using the platform steps above.
4. Launch QuantCode and confirm the version in the About dialog.

Reinstalling the application does not remove workspace settings or session
state. QuantCode keeps its desktop data under the stable product id
`org.hkust.quantcode` and does not share updater state with OpenCode. Back up
that directory before a manual rollback:

- macOS: `~/Library/Application Support/org.hkust.quantcode`
- Windows: `%APPDATA%\org.hkust.quantcode`
- Linux: `${XDG_CONFIG_HOME:-~/.config}/org.hkust.quantcode`

Do not install an older build over a newer one without a backup. Downgrades are
not an automatic or supported release path.
