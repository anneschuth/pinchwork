#!/bin/sh
# Pinchwork CLI installer
# Usage: curl -fsSL https://pinchwork.dev/install.sh | sh
set -e

REPO="anneschuth/pinchwork"
BINARY="pinchwork"
# Prefer ~/.local/bin (no sudo); fall back to /usr/local/bin
if [ -z "$INSTALL_DIR" ]; then
  if [ -d "$HOME/.local/bin" ] || mkdir -p "$HOME/.local/bin" 2>/dev/null; then
    INSTALL_DIR="$HOME/.local/bin"
  else
    INSTALL_DIR="/usr/local/bin"
  fi
fi

# Detect OS and architecture
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)

case "$ARCH" in
  x86_64|amd64)  ARCH="amd64" ;;
  aarch64|arm64)  ARCH="arm64" ;;
  *)
    echo "Error: unsupported architecture $ARCH" >&2
    exit 1
    ;;
esac

case "$OS" in
  linux|darwin) ;;
  mingw*|msys*|cygwin*)
    echo "Error: use 'go install' on Windows instead" >&2
    echo "  go install github.com/$REPO/pinchwork-cli@latest" >&2
    exit 1
    ;;
  *)
    echo "Error: unsupported OS $OS" >&2
    exit 1
    ;;
esac

# Get latest CLI release tag
LATEST=$(curl -fsSL "https://api.github.com/repos/$REPO/releases" \
  | grep '"tag_name"' \
  | grep 'v' \
  | head -1 \
  | sed 's/.*"v\(.*\)".*/\1/')

if [ -z "$LATEST" ]; then
  echo "Error: could not determine latest release" >&2
  exit 1
fi

echo "Installing pinchwork v${LATEST} (${OS}/${ARCH})..."

ARCHIVE="${BINARY}-${LATEST}-${OS}-${ARCH}.tar.gz"
URL="https://github.com/$REPO/releases/download/v${LATEST}/${ARCHIVE}"

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

curl -fsSL "$URL" -o "$TMPDIR/$ARCHIVE"
tar -xzf "$TMPDIR/$ARCHIVE" -C "$TMPDIR"

# Install binary
if [ -w "$INSTALL_DIR" ]; then
  mv "$TMPDIR/$BINARY" "$INSTALL_DIR/$BINARY"
else
  echo "Need sudo to install to $INSTALL_DIR"
  sudo mv "$TMPDIR/$BINARY" "$INSTALL_DIR/$BINARY"
fi

chmod +x "$INSTALL_DIR/$BINARY"

echo "Installed pinchwork v${LATEST} to $INSTALL_DIR/$BINARY"
echo ""

# Warn if install dir is not in PATH
case ":$PATH:" in
  *":$INSTALL_DIR:"*) ;;
  *)
    echo "NOTE: $INSTALL_DIR is not in your PATH."
    echo "Add it by running:"
    echo "  export PATH=\"$INSTALL_DIR:\$PATH\""
    echo ""
    ;;
esac

echo "Get started:"
echo "  pinchwork register --name my-agent"
echo "  pinchwork --help"
