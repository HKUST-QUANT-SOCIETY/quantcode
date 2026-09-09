# QuantCode source and license notices

QuantCode is maintained in https://github.com/HKUST-QUANT-SOCIETY/quantcode.
Its desktop interface and execution services incorporate the OpenCode source
maintained in this repository, originally from https://github.com/anomalyco/opencode.
QuantCode's integration and organization rules do not change the original
copyright ownership or license of that source.

The following files are copied without modifying their contents:

- `quantcode-LICENSE.txt`: the repository root `LICENSE`.
- `opencode-LICENSE.txt`: `frontend/LICENSE`.
- `opencode-ui-LICENSE.txt`: `frontend/packages/ui/LICENSE`.
- `opencode-http-recorder-LICENSE.txt`: `frontend/packages/http-recorder/LICENSE`.

`source-licenses.json` identifies these repository paths and the SHA-256 of the
copied bytes. The release's existing `release-manifest.json` identifies the
QuantCode source commit, workflow and installer hashes. These notices identify
source attribution; they are not a separate release or update mechanism.

Electron, Chromium and other dependencies retain their own licenses and notices
in their distributed package files. The documents above preserve the notices
for the repository-owned source and incorporated OpenCode source; they do not
replace dependency-specific license terms.

QuantCode's desktop package includes its execution server. Normal use does not
require a separately installed OpenCode application. A configured research host
may provide organization services; its deployment and credentials remain under
the organization's control.
