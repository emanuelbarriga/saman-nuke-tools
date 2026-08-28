#!/usr/bin/env bash
#
# setup_artista.sh — Configura SamanTools en ~/.nuke con ACTUALIZACION AUTOMATICA
# via GitHub (repo publico). El artista lo ejecuta UNA sola vez.
#
# Uso (en la maquina del artista, macOS o Linux):
#   bash setup_artista.sh https://github.com/TU_ORG/saman-nuke-tools.git
#
# Despues de esto:
#   - Copia el bootstrap a ~/.nuke/menu.py (NO se toca nunca mas)
#   - Clona el repo a ~/.nuke/SamanTools (checkout local)
#   - Cada vez que el artista abre Nuke, el menú se actualiza solo
#     (git pull silencioso, max. 1 vez cada 6h).
#
set -euo pipefail

REPO_URL="${1:?Uso: setup_artista.sh <URL del repo en GitHub>}"
TOOLS_DIR="$HOME/.nuke"
TOOLS_CHECKOUT="$TOOLS_DIR/SamanTools"
BOOTSTRAP="$(cd "$(dirname "$0")" && pwd)/bootstrap/menu.py"

echo "==> Preparando SamanTools en $TOOLS_DIR ..."
mkdir -p "$TOOLS_DIR"

# 1) Bootstrap menu.py (solo si no existe o es el viejo copiado de install.sh)
if [ ! -f "$TOOLS_DIR/menu.py" ] || grep -q "SamanTools.registro" "$TOOLS_DIR/menu.py" 2>/dev/null; then
  cp "$BOOTSTRAP" "$TOOLS_DIR/menu.py"
  echo "    menu.py bootstrap instalado."
else
  echo "    menu.py bootstrap ya presente."
fi

# 2) Checkout git del repo (clone si falta, pull si ya existe)
if [ ! -d "$TOOLS_CHECKOUT/.git" ]; then
  echo "    Clonando el repo (primera vez)..."
  git clone --depth 1 "$REPO_URL" "$TOOLS_CHECKOUT"
else
  echo "    Checkout existente, actualizando..."
  git -C "$TOOLS_CHECKOUT" pull --ff-only --quiet || true
fi

# Inyectar el REPO_URL correcto en el bootstrap (si el template tenia TU_ORG)
sed -i.bak "s|https://github.com/TU_ORG/saman-nuke-tools.git|$REPO_URL|" "$TOOLS_DIR/menu.py" 2>/dev/null || true

echo ""
echo "==> LISTO. Reinicia Nuke."
echo "    A partir de ahora SamanTools se actualiza automaticamente."
echo "    (El artista NO necesita tocar nada nunca mas.)"
echo "    Este mensaje NO debe mostrarse en otra maquina..."