"""Desktop GitHub adapter. Credentials stay on the host; roster remains authoritative."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import hashlib
import re
import stat

from quantcode.identity_login import read_session_file
from quantcode.github_credentials import subject_token


def _owner_digest(context: dict) -> str:
    owner = {field: context.get(field) for field in (
        "actor_id", "group", "role", "workspace_id", "workspace_path", "github_subject",
    )}
    owner["resource_scopes"] = sorted(set(context.get("resource_scopes") or []))
    return hashlib.sha256(json.dumps(owner, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def import_token(context: dict, payload: dict) -> dict:
    """Main-process credential import; invalid input never replaces a mapping."""
    from quantcode.identity_login import _session_record
    from quantcode.github_credentials import _credential_directory, _private_text
    from runner.execution_lock import execution_lock
    import httpx

    token, expected = payload.get("token"), payload.get("owner_digest")
    if set(payload) != {"token", "owner_digest"} or not isinstance(token, str) or not token or len(token) > 16384 or re.search(r"\s", token):
        raise ValueError("invalid GitHub credential import")
    if expected != _owner_digest(context):
        raise PermissionError("GitHub 接入所属身份已变化。")
    subject = context.get("github_subject")
    if not isinstance(subject, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", subject):
        raise PermissionError("组织身份未绑定 GitHub 账号。")
    identity_file = Path(os.environ["QUANTCODE_IDENTITY_SESSION_FILE"])
    record = _session_record(identity_file)

    def validate() -> None:
        current = read_session_file(identity_file)
        if current["session_id"] != context["session_id"] or _owner_digest(current) != expected or _session_record(identity_file) != record:
            raise PermissionError("GitHub 接入期间组织身份已变化。")

    validate()
    with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
        response = client.get("https://api.github.com/user", headers={"Authorization": f"Bearer {token}",
                              "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    if response.status_code != 200 or str(response.json().get("login", "")).lower() != subject.lower():
        raise PermissionError("GitHub 凭据与当前组织账号不一致。")
    path = Path(os.environ["QUANTCODE_GITHUB_CREDENTIALS_FILE"])
    if not path.is_absolute() or path.parent.resolve() != path.parent:
        raise PermissionError("GitHub 凭据目录必须是宿主私有路径。")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = _credential_directory(path.parent)

    def validate_directory() -> None:
        current = _credential_directory(path.parent)
        if (current.st_dev, current.st_ino) != (directory.st_dev, directory.st_ino):
            raise PermissionError("GitHub 凭据目录已变化，请重新连接。")

    def replace(content: str) -> None:
        validate_directory()
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".github-import-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            validate_directory()
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    with execution_lock(path, "github-credential-import"):
        validate_directory()
        validate()
        if path.exists() and (path.is_symlink() or not stat.S_ISREG(path.stat().st_mode)):
            raise PermissionError("GitHub 凭据映射必须是私有普通文件。")
        previous = _private_text(path) if path.exists() else None
        mapping = json.loads(previous) if previous is not None else {"subjects": {}}
        if not isinstance(mapping, dict) or not isinstance(mapping.get("subjects"), dict):
            raise ValueError("invalid GitHub credential mapping")
        # Store each verified token at an immutable private path. Replacing a
        # mapping must not overwrite the token that its old version references.
        target = path.parent / f"github-{subject.lower()}-{hashlib.sha256(token.encode()).hexdigest()}.token"
        if target.exists():
            if target.is_symlink() or _private_text(target, 16384) != token:
                raise PermissionError("GitHub credential record conflicts")
        else:
            descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(token)
                stream.flush()
                os.fsync(stream.fileno())
        updated = json.dumps({**mapping, "subjects": {**mapping["subjects"], subject.lower(): {"token_file": str(target)}}}, ensure_ascii=False)
        validate()
        validate_directory()
        if (_private_text(path) if path.exists() else None) != previous:
            raise PermissionError("GitHub 凭据映射已变化，请重新连接。")
        replace(updated)
        try:
            validate()
            validate_directory()
        except Exception:
            # Only undo our own exact mapping; never overwrite a newer writer.
            if _private_text(path) == updated:
                if previous is None:
                    path.unlink()
                else:
                    replace(previous)
            raise
    return {"status": "connected", "subject": subject}


def verified_token(context: dict, *, local: bool = False) -> str:
    from tools.admin._register import _gh_get
    subject = context.get("github_subject")
    if not subject:
        raise PermissionError("当前组织身份尚未绑定 GitHub 账号，请联系管理员更新成员名册。")
    token = None if local else subject_token(context)
    if not token:
        if not local:
            raise PermissionError("当前研究宿主尚未连接该 GitHub 账号，请选择登录方式。")
        active = subprocess.run(["gh", "api", "user", "--hostname", "github.com", "--jq", ".login"],
                                capture_output=True, text=True, timeout=15)
        if active.returncode != 0 or active.stdout.strip().lower() != subject.lower():
            raise PermissionError("浏览器授权的 GitHub 账号与组织名册不一致。")
        result = subprocess.run(["gh", "auth", "token", "--hostname", "github.com", "--user", subject],
                                capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            raise PermissionError("研究宿主未找到该账号刚完成的 GitHub 授权，请重试浏览器登录。")
        token = result.stdout.strip()
    if str(_gh_get("/user", token).get("login", "")).lower() != subject.lower():
        raise PermissionError("GitHub 账号与当前组织身份不一致，请使用名册绑定的账号登录。")
    return token


def save_token(context: dict, token: str) -> None:
    import_token(context, {"token": token, "owner_digest": _owner_digest(context)})


def execute(action: str, expected_session: str, payload: dict) -> dict:
    path = Path(os.environ["QUANTCODE_IDENTITY_SESSION_FILE"])
    context = read_session_file(path)
    if context["session_id"] != expected_session:
        raise PermissionError("登录身份已变化，请重新连接。")
    if action == "import":
        return import_token(context, payload)
    token = verified_token(context, local=action == "connect")
    # Never forward host secrets to a remote research process or include them in results.
    context["github_token"] = token
    if action in {"status", "local", "connect"}:
        result = {"status": "connected", "subject": context["github_subject"]}
    elif action == "commit":
        result = commit_detail(context, payload)
    else:
        from tools.pop._register import GraphArgs, ListPopsArgs, UpdatePopArgs, _graph, _list, _update
        schema, handler = {"get_gitgraph": (GraphArgs, _graph), "refresh_gitgraph": (GraphArgs, _graph), "list_pops": (ListPopsArgs, _list), "update_pop_status": (UpdatePopArgs, _update)}[action]
        if set(payload) - set(schema.model_fields):
            raise ValueError("不支持的 GitHub 请求参数")
        if action in {"get_gitgraph", "refresh_gitgraph"}:
            from runner.github_sync import sync_graph
            schema.model_validate(payload)
            result = sync_graph(context, refresh_limit=2 if action == "refresh_gitgraph" else 0)
        else:
            result = handler(schema.model_validate(payload), context)
    # Recheck revocation/session replacement before releasing data or persisting credentials.
    after = read_session_file(path)
    if after["session_id"] != expected_session:
        raise PermissionError("登录身份已变化，请重新连接。")
    if action in {"local", "connect"}:
        save_token(context, token)
    return result


def commit_detail(context: dict, payload: dict) -> dict:
    import re
    from tools.admin._register import GH_ORG, _visible_repos, _gh_get
    repo, sha = payload.get("repo", ""), payload.get("sha", "")
    if set(payload) != {"repo", "sha"} or not isinstance(repo, str) or not isinstance(sha, str):
        raise ValueError("invalid commit request")
    if not re.fullmatch(re.escape(GH_ORG) + r"/[A-Za-z0-9_.-]+", repo) or not re.fullmatch(r"[a-fA-F0-9]{40}", sha):
        raise ValueError("invalid repository or commit")
    repos, _ = _visible_repos(context, context["github_token"])
    if repo.lower() not in {str(item.get("full_name", "")).lower() for item in repos}:
        raise PermissionError("当前账号无权查看该仓库。")
    data = _gh_get(f"/repos/{repo}/commits/{sha}?per_page=100", context["github_token"])
    info = data.get("commit") or {}
    files = data.get("files") or []
    if data.get("sha") != sha:
        raise ValueError("commit response mismatch")
    return {"sha": sha, "message": info.get("message", ""),
            "author": (info.get("author") or {}).get("name"), "date": (info.get("author") or {}).get("date"),
            "files": [{key: file.get(key) for key in ("filename", "status", "additions", "deletions", "patch")} for file in files],
            "has_more": len(files) >= 100}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=["import", "commit", "status", "local", "connect", "get_gitgraph", "refresh_gitgraph", "list_pops", "update_pop_status"], required=True)
    parser.add_argument("--session", required=True)
    args = parser.parse_args()
    lock = None
    if args.action == "refresh_gitgraph":
        import hashlib
        root = Path(__file__).resolve().parents[1] / ".quantcode"
        root.mkdir(exist_ok=True)
        lock = open(root / ("github-sync-" + hashlib.sha256(args.session.encode()).hexdigest() + ".lock"), "a+b")
        # OS locks are released on process exit, including crashes.
        lock.write(b"0")
        lock.flush()
        try:
            if os.name == "nt":
                import msvcrt
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock.close()
            return
    try:
        result = execute(args.action, args.session, {} if args.action == "refresh_gitgraph" else json.load(sys.stdin))
    except PermissionError as exc:
        result = {"status": "disconnected", "error": str(exc)}
    except FileNotFoundError:
        result = {"status": "disconnected", "error": "研究宿主的 GitHub CLI 或身份配置不可用，请检查安装与登录状态。"}
    except Exception:
        result = {"status": "error", "error": "GitHub 请求失败，请检查凭据有效期、网络与组织授权。"}
    print(json.dumps(result, ensure_ascii=False, default=str))
    if lock:
        lock.close()
    if args.action == "get_gitgraph" and result.get("refresh_pending"):
        subprocess.Popen([sys.executable, "-m", "quantcode.github_host", "--action", "refresh_gitgraph", "--session", args.session],
                         cwd=Path(__file__).resolve().parents[1], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

if __name__ == "__main__":
    main()
