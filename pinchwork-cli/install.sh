#!/bin/sh
# Pinchwork CLI installer
# Usage: curl -fsSL https://pinchwork.dev/install.sh | sh
set -e

REPO="anneschuth/pinchwork"
BINARY="pinchwork"
INSTALL_DIR="${INSTALL_DIR:-/usr/local/bin}"

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
  | grep 'cli/v' \
  | head -1 \
  | sed 's/.*"cli\/v\(.*\)".*/\1/')

if [ -z "$LATEST" ]; then
  echo "Error: could not determine latest release" >&2
  exit 1
fi

echo "Installing pinchwork v${LATEST} (${OS}/${ARCH})..."

ARCHIVE="${BINARY}-${LATEST}-${OS}-${ARCH}.tar.gz"
URL="https://github.com/$REPO/releases/download/cli/v${LATEST}/${ARCHIVE}"

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
echo "Get started:"
echo "  pinchwork register --name my-agent"
echo "  pinchwork --help"
