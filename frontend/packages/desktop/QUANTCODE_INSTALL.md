# Install QuantCode Desktop

QuantCode Desktop is distributed to authorized HKUST Quant Society members
through the public `HKUST-QUANT-SOCIETY/quantcode` GitHub Releases page. A
workflow artifact from a pull request is an unsigned QA build, not a formal
release. Formal releases have `distribution.releaseClass=approved-release`.
The explicitly labeled **QuantCode Test V1.2** prerelease uses version
`1.2.0-test.5`, tag `quantcode-v1.2.0-test.5`, and `releaseClass=internal-test`.
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

For Test V1.2, verify the exact `quantcode-v1.2.0-test.5` prerelease and source
commit. Its manifest must report `internal-test`, `unsigned-test` for macOS and
Windows, and `updateFeed=disabled`. Checksums and GitHub provenance identify the
tested build; they do not turn an unsigned installer into a signed one.

## Install

### macOS

Open the DMG, drag **QuantCode** to **Applications**, then launch QuantCode from
Applications. The formal package is signed with Developer ID and notarized by
Apple. Test V1.2 is unsigned and may require an explicit macOS security prompt
to be approved by the member after verifying the release. If organization policy
blocks unsigned applications, use an approved signed release instead. Do not
disable Gatekeeper globally.

### Windows

Run the x64 installer. QuantCode is installed for the current user and appears
in the Start menu. The formal installer and `QuantCode.exe` are signed with the
publisher recorded in the release manifest.

Test V1.2 is unsigned and may show a SmartScreen warning. Verify the source and
checksum before choosing whether to run it; managed computers may require IT
approval. From `1.2.0-test.4`, a stopped **OpenSSH Authentication Agent** is
handled in the login form: click **启用 SSH Agent 并继续登录** and confirm the
Windows administrator prompt. QuantCode enables automatic startup, starts the
service, verifies that it is accessible, and retries the selected key. Cancelling
the system prompt leaves a retry option. Closing the login page does not resume
login in the background.

If **OpenSSH Client** is missing, use the in-app **打开 Windows 可选功能** button,
install the client, then select **重新检查并继续登录**. Git Bash/WSL tools do not
replace the native Windows client required by this desktop build.

For older versions or manual service setup, an administrator can run:

```powershell
Set-Service -Name ssh-agent -StartupType Automatic
Start-Service ssh-agent
```

The desktop uses `%SystemRoot%\System32\OpenSSH\ssh-add.exe` and
`ssh-keygen.exe`. Select your registered private key through **重新登录**, or
choose **使用已有 SSH 身份** after loading it with that system `ssh-add.exe`; Git Bash's separate
agent is not the Windows service used by the desktop. An already unlocked key is reused from the system Agent. For a locked key, use the desktop terminal-unlock action or run `ssh-add.exe` in a terminal, then retry the selected identity. PEM conversion and key renaming are not required.

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
Python checkout. Select your registered private key or an existing SSH Agent
identity. QuantCode discovers the built-in organization servers using your
existing SSH username, then lists the authorized group/workspace choices.
Selecting a group completes authentication and enters its workspace. Members
do not enter host URLs or internal research usernames. The organization test
model is preconfigured; personal provider credentials are optional. The host
owns Python organization services, published tools and workspace grants.
Keep private keys in the operating-system credential or SSH store, never in a
project file or the desktop package.

## Upgrade

Automatic updates are disabled for the current release workflows, including
Test V1.2. To upgrade:

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
