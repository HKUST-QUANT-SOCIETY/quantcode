#!/usr/bin/env bash

# Strict deployment preflight. Development may run without identity/provider
# configuration; this command intentionally refuses to call that state ready.
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

failures=0
info() { printf '[INFO] %s\n' "$1"; }
fail() { printf '[FAIL] %s\n' "$1" >&2; failures=$((failures + 1)); }
pass() { printf '[PASS] %s\n' "$1"; }

python_bin="${QUANTCODE_HOST_PYTHON:-${QUANTCODE_PYTHON:-$project_root/.venv/bin/python}}"
if [[ ! -x "$python_bin" ]]; then
  fail "QUANTCODE_HOST_PYTHON is not an executable Python 3.12+ path: $python_bin"
else
  if PYTHONPATH="$project_root" "$python_bin" -c 'import quantcode.mcp_server, runner' >/dev/null 2>&1; then
    pass "Python and QuantCode MCP import"
  else
    fail "QuantCode MCP cannot be imported with $python_bin"
  fi
fi

roster="${QUANTCODE_ROSTER_FILE:-$project_root/.opencode/authorized_groups.yaml}"
if [[ ! -f "$roster" ]]; then
  fail "formal roster is missing: $roster"
else
  set +e
  roster_check="$($python_bin -c 'import os, stat, sys; from pathlib import Path; path=Path(sys.argv[1]); mode=stat.S_IMODE(path.stat().st_mode); message=f"roster permissions are {oct(mode)}, require owner-only access" if mode & 0o077 else ("roster is not owned by the current user" if path.stat().st_uid != os.getuid() else ""); print(message) if message else None; sys.exit(1 if message else 0)' "$roster" 2>&1)"
  roster_status=$?
  set -e
  if (( roster_status != 0 )); then fail "${roster_check:-roster validation failed}"; else pass "formal roster exists with owner-only permissions"; fi
fi

required=(QUANTCODE_HOST_PYTHON QUANTCODE_BACKEND_ROOT QUANTCODE_PUBLIC_KEY_FILE QUANTCODE_IDENTITY_SESSION_FILE QUANTCODE_GATEWAY_URL)
for name in "${required[@]}"; do
  value="${!name:-}"
  [[ -n "$value" ]] || fail "$name is not configured"
done

if [[ -n "${QUANTCODE_GITHUB_CREDENTIALS_FILE:-}" ]]; then
  if [[ "$QUANTCODE_GITHUB_CREDENTIALS_FILE" != /* || ! -r "$QUANTCODE_GITHUB_CREDENTIALS_FILE" ]]; then
    fail "configured GitHub credential mapping is not an absolute readable file"
  else
    pass "GitHub credential mapping is configured"
  fi
else
  info "GitHub credential mapping not configured; authenticated GitGraph/Pop will remain unavailable"
fi

if [[ -n "${QUANTCODE_DEPLOY_URL:-}" ]]; then
  pass "production deploy handoff is configured"
else
  info "production deploy handoff not configured; Admin requests remain STAGING"
fi

for name in QUANTCODE_BACKEND_ROOT QUANTCODE_PUBLIC_KEY_FILE QUANTCODE_IDENTITY_SESSION_FILE; do
  value="${!name:-}"
  [[ -z "$value" ]] && continue
  [[ "$value" = /* ]] || fail "$name must be an absolute path"
done

if [[ -n "${QUANTCODE_BACKEND_ROOT:-}" && ! -d "$QUANTCODE_BACKEND_ROOT" ]]; then
  fail "QUANTCODE_BACKEND_ROOT does not exist: $QUANTCODE_BACKEND_ROOT"
fi
if [[ -n "${QUANTCODE_PUBLIC_KEY_FILE:-}" && ! -r "$QUANTCODE_PUBLIC_KEY_FILE" ]]; then
  fail "configured SSH public key is not readable: $QUANTCODE_PUBLIC_KEY_FILE"
fi
if [[ -n "${QUANTCODE_IDENTITY_SESSION_FILE:-}" ]]; then
  session_parent="$(dirname "$QUANTCODE_IDENTITY_SESSION_FILE")"
  [[ -d "$session_parent" && -w "$session_parent" ]] || fail "identity session directory is not writable: $session_parent"
fi

gateway="${QUANTCODE_GATEWAY_URL:-}"
if [[ -n "$gateway" ]]; then
  gateway_status="$(curl --noproxy '*' -sS -o /dev/null -w '%{http_code}' --max-time 5 "$gateway/session" 2>/dev/null || true)"
  if [[ "$gateway_status" == "200" || "$gateway_status" == "401" ]]; then
    pass "identity gateway is reachable ($gateway_status from /session)"
  else
    fail "identity gateway is not reachable: $gateway (HTTP ${gateway_status:-no response})"
  fi
fi

if [[ "${QUANTCODE_REQUIRE_INSTALLER:-false}" == "true" ]]; then
  installer_dir="${QUANTCODE_INSTALLER_DIR:-$project_root/frontend/packages/desktop/dist}"
  if [[ ! -d "$installer_dir" ]]; then
    fail "installer output directory is missing: $installer_dir"
  else
    shopt -s nullglob
    installers=("$installer_dir"/*.dmg "$installer_dir"/*.zip "$installer_dir"/*.exe "$installer_dir"/*.AppImage "$installer_dir"/*.deb "$installer_dir"/*.rpm)
    shopt -u nullglob
    if (( ${#installers[@]} == 0 )); then fail "no installer artifact found in $installer_dir"; else pass "installer artifacts found (${#installers[@]})"; fi
  fi
else
  info "installer gate skipped for current server/API rollout (set QUANTCODE_REQUIRE_INSTALLER=true to enable)"
fi

if [[ "${QUANTCODE_REQUIRE_SIGNED:-false}" == "true" ]]; then
  if [[ "$(uname -s)" == "Darwin" ]] && command -v codesign >/dev/null 2>&1; then
    app="$installer_dir/mac-arm64/QuantCode.app"
    [[ -d "$app" ]] && codesign --verify --deep --strict "$app" >/dev/null 2>&1 && pass "macOS signature verified" || fail "signed macOS QuantCode.app was not verified"
  else
    fail "QUANTCODE_REQUIRE_SIGNED=true requires platform-specific CI signature verification"
  fi
else
  info "signature gate not requested; unsigned artifacts are QA-only"
fi

if (( failures > 0 )); then
  printf '\nDeployment readiness: FAIL (%s checks)\n' "$failures" >&2
  exit 1
fi

printf '\nDeployment readiness: PASS\n'
