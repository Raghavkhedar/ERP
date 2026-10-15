#!/usr/bin/env bash
set -euo pipefail

TAILWIND_VERSION="4.3.3"

mkdir -p bin
curl -fsSL -o bin/tailwindcss \
  "https://github.com/tailwindlabs/tailwindcss/releases/download/v${TAILWIND_VERSION}/tailwindcss-linux-x64"
chmod +x bin/tailwindcss
bin/tailwindcss --help | head -n 1
