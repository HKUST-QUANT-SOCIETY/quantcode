# Install QuantCode Desktop

QuantCode Desktop is distributed to authorized HKUST Quant Society members
through the public `HKUST-QUANT-SOCIETY/quantcode` GitHub Releases page. A
workflow artifact from a pull request is an unsigned QA build, not a formal
release. Formal releases have `distribution.releaseClass=approved-release`.
The explicitly labeled **QuantCode Test V1.0** prerelease uses version
`1.0.0-test.1`, tag `quantcode-v1.0.0-test.1`, and `releaseClass=internal-test`.
It provides unsigned macOS arm64/x64 and Windows x64 packages for member testing;
it does not claim Apple notarization or a Windows publisher signature.

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
release. The public release downloads do not require repository credentials.

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
gh attestation verify ./quantcode-0.1.0-mac-arm64.dmg -R HKUST-QUANT-SOCIETY/quantcode
```

For formal releases, the macOS manifest must report `developer-id-notarized`; the Windows manifest
must report `azure-trusted-signing`. Linux is intentionally reported as
`approved-platform-unsigned`: verify both SHA-256 and GitHub provenance before
installing it.

For Test V1.0, verify the exact `quantcode-v1.0.0-test.1` prerelease and source
commit. Its manifest must report `internal-test`, `unsigned-test` for macOS and
Windows, and `updateFeed=disabled`. Checksums and GitHub provenance identify the
tested build; they do not turn an unsigned installer into a signed one.

## Install

### macOS

Open the DMG, drag **QuantCode** to **Applications**, then launch QuantCode from
Applications. The formal package is signed with Developer ID and notarized by
Apple. Test V1.0 is unsigned and may require an explicit macOS security prompt
to be approved by the member after verifying the release. If organization policy
blocks unsigned applications, use an approved signed release instead. Do not
disable Gatekeeper globally.

### Windows

Run the x64 installer. QuantCode is installed for the current user and appears
in the Start menu. The formal installer and `QuantCode.exe` are signed with the
publisher recorded in the release manifest.

Test V1.0 is unsigned and may show a SmartScreen warning. Verify the source and
checksum before choosing whether to run it; managed computers may require IT
approval. Install **OpenSSH Client** in Windows Optional Features, then start
the **OpenSSH Authentication Agent** service. In an administrator PowerShell:

```powershell
Set-Service -Name ssh-agent -StartupType Automatic
Start-Service ssh-agent
```

The desktop uses `%SystemRoot%\System32\OpenSSH\ssh-add.exe` and
`ssh-keygen.exe`. Import your registered key through **From File / Import SSH
Private Key**, or load it with that system `ssh-add.exe`; Git Bash's separate
agent is not the Windows service used by the desktop. A passphrase-protected
key may need to be unlocked with `ssh-add.exe` in a terminal first.

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
Python checkout. Connect to the QuantCode execution host supplied by the
organization and sign in with your registered SSH identity. The roster binds
your group automatically. Add one URL/API Key connection in QuantCode model
settings. The host owns Python organization services, published component
tools and workspace grants; members do not install another OpenCode product,
choose a group, or configure a second Runner model key.
Keep private keys in the operating-system credential or SSH store, never in a
project file or the desktop package.

## Upgrade

Automatic updates are disabled for the current release workflows, including
Test V1.0. To upgrade:

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
