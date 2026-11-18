#!/usr/bin/env bash
# Bump the bundled open-code-review CLI and the vendored post_review.py to a release (default: the latest).
# Usage: bump_ocr.sh [vX.Y.Z]
# Edits docker/Dockerfile (OCR_VERSION + both SHA-256 pins), third_party/open_code_review/{post_review.py,LICENSE,
# README.md}, and probes the real binary for the CLI surface pr_agent uses. Prints a report; exit 1 on any failed probe.
set -euo pipefail

REPO="alibaba/open-code-review"
cd "$(git rev-parse --show-toplevel)"
DOCKERFILE="docker/Dockerfile"
VENDOR="third_party/open_code_review"

CURRENT="$(sed -n 's/^ARG OCR_VERSION=//p' "$DOCKERFILE")"
TARGET="${1:-$(gh release view -R "$REPO" --json tagName -q .tagName)}"
echo "current=$CURRENT target=$TARGET"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
gh release view "$TARGET" -R "$REPO" --json assets -q '.assets[].name' > "$WORK/assets.txt"
for asset in opencodereview-linux-amd64 opencodereview-linux-arm64 sha256sum.txt; do
  grep -qx "$asset" "$WORK/assets.txt" || { echo "Release $TARGET lacks asset $asset; asset layout changed" >&2; exit 1; }
done
gh release download "$TARGET" -R "$REPO" -p sha256sum.txt -D "$WORK"
sha_for() { awk -v f="$1" '$2 == f || $2 == "*"f {print $1}' "$WORK/sha256sum.txt"; }
SHA_AMD64="$(sha_for opencodereview-linux-amd64)"
SHA_ARM64="$(sha_for opencodereview-linux-arm64)"
[ -n "$SHA_AMD64" ] && [ -n "$SHA_ARM64" ] || { echo "sha256sum.txt lacks a linux asset line" >&2; exit 1; }

# Probe the real binary for the host architecture.
case "$(uname -m)" in x86_64) ARCH=amd64 ;; aarch64|arm64) ARCH=arm64 ;; *) echo "unsupported host arch" >&2; exit 1 ;; esac
gh release download "$TARGET" -R "$REPO" -p "opencodereview-linux-$ARCH" -D "$WORK"
echo "$(sha_for "opencodereview-linux-$ARCH")  $WORK/opencodereview-linux-$ARCH" | sha256sum -c - >/dev/null
chmod +x "$WORK/opencodereview-linux-$ARCH"
OCR="$WORK/opencodereview-linux-$ARCH"
PROBE_FAIL=0
probe() {  # probe <description> <needle> <ocr args...>
  local desc="$1" needle="$2"; shift 2
  if HOME="$WORK/home" "$OCR" "$@" 2>&1 | grep -qF -- "$needle"; then echo "  ok   $desc"
  else echo "  FAIL $desc ('$needle' not in \`ocr $*\`)"; PROBE_FAIL=1; fi
}
echo "binary: $(HOME="$WORK/home" "$OCR" version 2>&1 | head -n 1)"
echo "CLI surface used by pr_agent/commands/pr_ocr_review.py:"
for flag in --from --to --format --audience --rule; do probe "review $flag" "$flag" review --help; done
probe "config set" "set" config --help
probe "llm test" "test" llm --help
for key in llm.url llm.auth_token llm.model llm.protocol language llm.extra_body; do
  probe "config key $key" "$key" config set --help
done

# Vendored poster and license, from the same tag.
RAW="https://raw.githubusercontent.com/$REPO/$TARGET"
curl -fsSL -o "$WORK/post_review.py" "$RAW/examples/gitlab_ci/post_review.py"
curl -fsSL -o "$WORK/LICENSE" "$RAW/LICENSE"
OLD_POST_SHA="$(sha256sum "$VENDOR/post_review.py" | cut -d' ' -f1)"
NEW_POST_SHA="$(sha256sum "$WORK/post_review.py" | cut -d' ' -f1)"
cp "$WORK/post_review.py" "$VENDOR/post_review.py"
cp "$WORK/LICENSE" "$VENDOR/LICENSE"

TAG_REF="$(gh api "repos/$REPO/git/ref/tags/$TARGET" -q '.object.type + " " + .object.sha')"
TAG_TYPE="${TAG_REF%% *}"; TAG_SHA="${TAG_REF#* }"
if [ "$TAG_TYPE" = "tag" ]; then
  COMMIT_SHA="$(gh api "repos/$REPO/git/tags/$TAG_SHA" -q .object.sha)"
  TAG_LINE="- Tag: \`$TARGET\` (annotated tag object \`$TAG_SHA\`)"
else
  COMMIT_SHA="$TAG_SHA"
  TAG_LINE="- Tag: \`$TARGET\` (lightweight tag)"
fi

sed -i -E \
  -e "s#^ARG OCR_VERSION=.*#ARG OCR_VERSION=$TARGET#" \
  -e "s#^ARG OCR_SHA256_AMD64=.*#ARG OCR_SHA256_AMD64=$SHA_AMD64#" \
  -e "s#^ARG OCR_SHA256_ARM64=.*#ARG OCR_SHA256_ARM64=$SHA_ARM64#" \
  "$DOCKERFILE"
sed -i -E \
  -e "s#(post_review\.py\`?: ?)?https://raw\.githubusercontent\.com/$REPO/[^/]+/#https://raw.githubusercontent.com/$REPO/$TARGET/#" \
  -e "s#^- Tag: .*#$TAG_LINE#" \
  -e "s#^- Upstream commit of the tag: .*#- Upstream commit of the tag: \`$COMMIT_SHA\`#" \
  -e "s#^- sha256 of \`post_review\.py\`: .*#- sha256 of \`post_review.py\`: \`$NEW_POST_SHA\`#" \
  "$VENDOR/README.md"

echo
echo "Dockerfile: OCR_VERSION $CURRENT -> $TARGET, amd64=$SHA_AMD64 arm64=$SHA_ARM64"
if [ "$OLD_POST_SHA" = "$NEW_POST_SHA" ]; then
  echo "post_review.py: unchanged ($NEW_POST_SHA)"
else
  echo "post_review.py: CHANGED $OLD_POST_SHA -> $NEW_POST_SHA; review: git diff -- $VENDOR/post_review.py"
fi
git diff --stat -- "$DOCKERFILE" "$VENDOR"
[ "$PROBE_FAIL" = 0 ] || { echo "Some CLI probes failed; see FAIL lines above." >&2; exit 1; }
