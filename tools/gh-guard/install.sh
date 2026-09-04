#!/usr/bin/env bash
# Put the gh shim ahead of the real gh on this machine's PATH. Idempotent.
#
# Usage: bash install.sh

set -eu
IMPL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$HOME/.local/bin"
ln -sfn "$IMPL_DIR/gh" "$HOME/.local/bin/gh"

echo "linked $HOME/.local/bin/gh -> $IMPL_DIR/gh"

case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "warning: $HOME/.local/bin is not on PATH; the shim will not be used" >&2 ;;
esac

if [ "$(command -v gh)" != "$HOME/.local/bin/gh" ]; then
  echo "warning: 'gh' still resolves to $(command -v gh); another directory shadows the shim" >&2
fi
