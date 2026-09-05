"""Complete Git tree discovery, including GitHub's truncated recursive response."""
from pathlib import PurePosixPath
from urllib.parse import quote


def repository_files(get, base: str, tree_sha: str) -> list[dict]:
    def entries(response):
        if not isinstance(response, dict) or not isinstance(response.get("tree"), list):
            raise ValueError("invalid GitHub tree response")
        for item in response["tree"]:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("sha"), str):
                raise ValueError("invalid GitHub tree entry")
            path = PurePosixPath(item["path"])
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError("invalid GitHub tree path")
        return response["tree"]

    response = get(f"{base}/git/trees/{quote(tree_sha, safe='')}?recursive=1")
    items = entries(response)
    if response.get("truncated") is False:
        return [item for item in items if item.get("type") == "blob" and item.get("mode") in {"100644", "100755"}]
    if response.get("truncated") is not True:
        raise ValueError("GitHub tree completeness is unknown")
    # GitHub explicitly requires non-recursive subtree traversal after truncation.
    # Cache objects by SHA, but expand each mount path: identical directories may
    # be mounted more than once in one repository.
    pending = [("", tree_sha, frozenset())]
    cache = {}
    files = []
    while pending:
        prefix, sha, ancestors = pending.pop()
        if sha in ancestors:
            raise ValueError("cyclic GitHub tree response")
        if sha not in cache:
            subtree = get(f"{base}/git/trees/{quote(sha, safe='')}")
            children = entries(subtree)
            if subtree.get("truncated") is not False:
                raise ValueError("non-recursive GitHub tree is incomplete")
            cache[sha] = children
        for item in cache[sha]:
            path = f"{prefix}{item['path']}"
            if item.get("type") == "tree":
                pending.append((path + "/", item["sha"], ancestors | {sha}))
            elif item.get("type") == "blob" and item.get("mode") in {"100644", "100755"}:
                files.append({**item, "path": path})
    return files
