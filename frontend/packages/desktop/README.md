# QuantCode Desktop

The QuantCode desktop app reuses the OpenCode Electron shell with QuantCode product identity, renderer, sidecar, and release controls.

See [QUANTCODE_INSTALL.md](./QUANTCODE_INSTALL.md) for member installation and manual upgrades, and [QUANTCODE_RELEASE.md](./QUANTCODE_RELEASE.md) for packaging, signing, updater, and release requirements. The active release targets are macOS arm64/x64, Windows x64, and Linux x64 (AppImage, DEB, and RPM). Pull requests run the unsigned matrix and packaged-launch smoke check, while only an approved, finalized release run may publish assets. Because the release repository is private, current installers ship with automatic updates disabled and are updated manually.

## Development

From the repository root:

```bash
bun install
bun run dev:desktop
```

## Build

From `packages/desktop`, run the `build` script to build the app's JS assets, then `package` to
bundle the assets as an application. The resulting app will be in `dist/`.

```bash
bun run build
bun run package
```

For a single platform, use `bun run package:mac`, `bun run package:win`, or `bun run package:linux`. CI exercises the real delivery container (mounted DMG, temporary NSIS install, or extracted AppImage), validates DEB/RPM contents, and uses a loopback-only random DevTools port to verify that the QuantCode renderer and sidecar start before accepting the artifact. Normal launches never expose that debug endpoint.
