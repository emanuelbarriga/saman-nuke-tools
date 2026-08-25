#!/usr/bin/env bash
#
# Instala saman-nuke-tools en ~/.nuke (macOS/Linux).
# Uso:
#   1) clona el repo
#   2) cd saman-nuke-tools && ./install.sh
# Esto copia menu.py y SamanTools/ a tu ~/.nuke; update = git pull + ./install.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
NUKE_DIR="$HOME/.nuke"

echo "==> Instalando saman-nuke-tools en $NUKE_DIR ..."
mkdir -p "$NUKE_DIR"

# backup por si ya existia
if [ -f "$NUKE_DIR/menu.py" ]; then
  cp "$NUKE_DIR/menu.py" "$NUKE_DIR/menu.py.bak.$(date +%Y%m%d%H%M%S)"
  echo "    (backup de menu.py previo creado)"
fi

cp -r "$REPO_DIR/SamanTools" "$NUKE_DIR/SamanTools"
find "$NUKE_DIR/SamanTools" -name '__pycache__' -type d -prune -exec rm -rf {} +
cp "$REPO_DIR/menu.py" "$NUKE_DIR/menu.py"

echo "==> Listo. Reinicia Nuke para que cargue SamanTools."
echo "==> (Alternativa sin copiar: setea NUKE_PATH=$REPO_DIR)"
