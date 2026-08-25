#!/usr/bin/env bash
set -euo pipefail

readonly test_deps="/srv/quant/envs/quantcode-testdeps-a3cd117-v1"
readonly python_base="/srv/quant/envs/python-3.12.13-review-stable"
readonly skill_bundle="/srv/quant/envs/mimocode-compose-0abfd8a"
readonly skill_bundle_sha256="d67ee430a68fe32822d74c726f980cf3cf7150d11b8cd9554804cc5a1acaa928"
readonly model_cache="/srv/quant/envs/quant-review-model-cache-a3cd117"
readonly tiktoken_cache_file="$model_cache/tiktoken/9b5ad71b2ce5302211f9c61530b329a4922fc6a4"
readonly tiktoken_cache_sha256="223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"
readonly chroma_model_dir="$model_cache/home/.cache/chroma/onnx_models/all-MiniLM-L6-v2"
readonly chroma_archive_sha256="913d7300ceae3b2dbc2c50d1de4baacab4be7b9380491c27fab7418616a16ec3"
readonly chroma_tree_sha256="21dd9e6ccaf517de6f60d3cb52e144a4f8703eec76da27d7fef5dcf665389004"

: "${GITHUB_WORKSPACE:?GITHUB_WORKSPACE is required}"
: "${QUANT_REVIEW_SANDBOX_PARENT:?QUANT_REVIEW_SANDBOX_PARENT is required}"

readonly sandbox_parent="/srv/quant/runner-sandboxes"
if [[ "$QUANT_REVIEW_SANDBOX_PARENT" != "$sandbox_parent" ]]; then
  echo "Refusing an unbounded sandbox parent: $QUANT_REVIEW_SANDBOX_PARENT" >&2
  exit 1
fi
if [[ "$(findmnt -n -T "$sandbox_parent" -o TARGET)" != "$sandbox_parent" ]] ||
   [[ "$(findmnt -n -T "$sandbox_parent" -o FSTYPE)" != "tmpfs" ]]; then
  echo "The review sandbox parent must be its own bounded tmpfs mount." >&2
  exit 1
fi

remove_sandbox_root() {
  local target="$1"
  case "$target" in
    "$sandbox_parent"/quantcode-pytest.*) ;;
    *)
      echo "Refusing to clean an unexpected sandbox path: $target" >&2
      return 1
      ;;
  esac
  if [[ ! -d "$target" || -L "$target" ]]; then
    echo "Refusing a non-directory sandbox cleanup target: $target" >&2
    return 1
  fi
  chmod -R u+w -- "$target"
  find "$target" -xdev -depth -delete
}

readonly runner_uid="$(id -u)"
while IFS= read -r -d '' stale_root; do
  remove_sandbox_root "$stale_root"
done < <(
  find "$sandbox_parent" -mindepth 1 -maxdepth 1 -xdev \
    -type d -user "$runner_uid" -name 'quantcode-pytest.*' -print0
)

readonly repo="$(pwd -P)"
if [[ "$repo" != "$GITHUB_WORKSPACE/quantcode" ]]; then
  echo "Refusing to test an unexpected checkout path: $repo" >&2
  exit 1
fi

readonly bundle_sha="$(cd "$skill_bundle" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | cut -d ' ' -f 1)"
if [[ "$bundle_sha" != "$skill_bundle_sha256" ]]; then
  echo "Pinned MimoCode skill bundle hash mismatch." >&2
  exit 1
fi

if [[ "$(sha256sum "$tiktoken_cache_file" | cut -d ' ' -f 1)" != "$tiktoken_cache_sha256" ]]; then
  echo "Pinned tiktoken cache hash mismatch." >&2
  exit 1
fi
if [[ "$(sha256sum "$chroma_model_dir/onnx.tar.gz" | cut -d ' ' -f 1)" != "$chroma_archive_sha256" ]]; then
  echo "Pinned Chroma archive hash mismatch." >&2
  exit 1
fi
readonly chroma_tree_sha="$(cd "$chroma_model_dir/onnx" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | cut -d ' ' -f 1)"
if [[ "$chroma_tree_sha" != "$chroma_tree_sha256" ]]; then
  echo "Pinned Chroma extracted model hash mismatch." >&2
  exit 1
fi

readonly sandbox_root="$(mktemp -d "$sandbox_parent/quantcode-pytest.XXXXXX")"
readonly rootfs="$sandbox_root/rootfs"
cleanup() {
  set +e
  case "$sandbox_root" in
    "$sandbox_parent"/quantcode-pytest.*)
      remove_sandbox_root "$sandbox_root"
      ;;
  esac
}
trap cleanup EXIT INT TERM

mkdir -p \
  "$rootfs/usr/bin" \
  "$rootfs/usr/lib" \
  "$rootfs/usr/lib64" \
  "$rootfs/usr/sbin" \
  "$rootfs/usr/share" \
  "$rootfs/etc" \
  "$rootfs/etc/ssl/certs" \
  "$rootfs/dev/shm" \
  "$rootfs/proc" \
  "$rootfs/tmp/home" \
  "$rootfs/workspace/quantcode" \
  "$rootfs/workspace/MiMo-Code/packages/opencode/src/skill/compose" \
  "$rootfs$test_deps" \
  "$rootfs$python_base" \
  "$rootfs$skill_bundle" \
  "$rootfs$model_cache"

ln -s usr/bin "$rootfs/bin"
ln -s usr/sbin "$rootfs/sbin"
ln -s usr/lib "$rootfs/lib"
ln -s usr/lib64 "$rootfs/lib64"
ln -s "$skill_bundle" "$rootfs/workspace/MiMo-Code/packages/opencode/src/skill/compose/.bundle"
printf 'root:x:0:0:root:/tmp/home:/bin/bash\n' > "$rootfs/etc/passwd"
printf 'root:x:0:\n' > "$rootfs/etc/group"
printf 'passwd: files\ngroup: files\nhosts: files\n' > "$rootfs/etc/nsswitch.conf"
ln -s /usr/share/zoneinfo/UTC "$rootfs/etc/localtime"
tar -C "$repo" -cf - . | tar -C "$rootfs/workspace/quantcode" -xf -

export QUANT_REVIEW_SANDBOX_ROOTFS="$rootfs"
export QUANT_REVIEW_TEST_DEPS="$test_deps"
export QUANT_REVIEW_PYTHON_BASE="$python_base"
export QUANT_REVIEW_SKILL_BUNDLE="$skill_bundle"
export QUANT_REVIEW_MODEL_CACHE="$model_cache"

unshare \
  --user \
  --map-root-user \
  --mount \
  --net \
  --ipc \
  --uts \
  --pid \
  --fork \
  --kill-child=TERM \
  /usr/bin/bash -c '
    set -euo pipefail
    mount --make-rprivate /

    for source in /usr/bin /usr/lib /usr/lib64 /usr/sbin /usr/share /etc/ssl/certs "$QUANT_REVIEW_TEST_DEPS" "$QUANT_REVIEW_PYTHON_BASE" "$QUANT_REVIEW_SKILL_BUNDLE" "$QUANT_REVIEW_MODEL_CACHE"; do
      target="$QUANT_REVIEW_SANDBOX_ROOTFS$source"
      mount --bind "$source" "$target"
      mount -o remount,bind,ro,nosuid,nodev "$target"
    done

    for device in null zero random urandom; do
      touch "$QUANT_REVIEW_SANDBOX_ROOTFS/dev/$device"
      mount --bind "/dev/$device" "$QUANT_REVIEW_SANDBOX_ROOTFS/dev/$device"
    done
    mount -t tmpfs -o size=64m,nosuid,nodev,noexec tmpfs "$QUANT_REVIEW_SANDBOX_ROOTFS/dev/shm"
    mount -t proc -o nosuid,nodev,noexec proc "$QUANT_REVIEW_SANDBOX_ROOTFS/proc"

    exec /usr/sbin/chroot "$QUANT_REVIEW_SANDBOX_ROOTFS" \
      /usr/bin/setpriv \
      --no-new-privs \
      --bounding-set=-all \
      --inh-caps=-all \
      --ambient-caps=-all \
      /usr/bin/env -i \
      PATH=/usr/bin:/bin \
      HOME="$QUANT_REVIEW_MODEL_CACHE/home" \
      TMPDIR=/tmp \
      TZ=UTC \
      LANG=C.UTF-8 \
      LC_ALL=C.UTF-8 \
      TIKTOKEN_CACHE_DIR="$QUANT_REVIEW_MODEL_CACHE/tiktoken" \
      LD_LIBRARY_PATH="$QUANT_REVIEW_PYTHON_BASE/lib" \
      PYTHONDONTWRITEBYTECODE=1 \
      PYTHONNOUSERSITE=1 \
      PYTHONSAFEPATH=1 \
      PYTHONPATH=. \
      /usr/bin/bash -c '"'"'
        ulimit -c 0
        ulimit -f 1048576
        ulimit -n 4096
        ulimit -u 512
        ulimit -t 900
        ulimit -v 8388608
        cd /workspace/quantcode
        exec "$@"
      '"'"' bash \
      "$QUANT_REVIEW_TEST_DEPS/bin/python" -m pytest -q tests
  '
