#!/usr/bin/env bash
#
# setup_artista.sh — Instala SamanTools desde cero y lo configura con
# auto-actualizacion via GitHub. El artista lo ejecuta UNA sola vez.
#
# Se puede ejecutar SIN tener el repo clonado:
#
#   macOS / Linux:
#     curl -sL https://raw.githubusercontent.com/emanuelbarriga/saman-nuke-tools/main/setup_artista.sh | bash
#
#   Windows (PowerShell):
#     Invoke-WebRequest -UseBasicParsing <misma URL> -OutFile setup_artista.sh ; bash setup_artista.sh
#
# Despues de esto:
#   - Clona el repo a ~/.nuke/SamanTools (checkout local).
#   - Copia el bootstrap a ~/.nuke/menu.py.
#   - Cada vez que el artista abre Nuke, recibe el menu SamanTools; si hay
#     actualizacion disponible, se le avisa y decide si actualizar.
#
set -euo pipefail

REPO_ORG="emanuelbarriga"
REPO_NAME="saman-nuke-tools"
BRANCH="main"
REPO_URL="https://github.com/${REPO_ORG}/${REPO_NAME}.git"
NUKE_DIR="$HOME/.nuke"
TOOLS_CHECKOUT="$NUKE_DIR/SamanTools"
# Sitio donde vive este script dentro del repo (para autodescargarse el bootstrap)
RAW="https://raw.githubusercontent.com/${REPO_ORG}/${REPO_NAME}/${BRANCH}"

echo "==> Preparando SamanTools en $NUKE_DIR ..."
mkdir -p "$NUKE_DIR"

# 1) Si este script se ejecuta desde un checkout local, usa su bootstrap;
#    si se ejecuta desde curl (sin repo), baja el bootstrap del repo.
BOOTSTRAP_SRC="${BOOTSTRAP_SRC:-}"
if [ -z "$BOOTSTRAP_SRC" ] && [ -f "$(dirname "$0")/bootstrap/menu.py" ]; then
  BOOTSTRAP_SRC="$(cd "$(dirname "$0")" && pwd)/bootstrap/menu.py"
fi
if [ -z "$BOOTSTRAP_SRC" ]; then
  TMP_BOOT="$(mktemp)"
  if curl -fsSL "$RAW/bootstrap/menu.py" -o "$TMP_BOOT" 2>/dev/null || \
     wget -q "$RAW/bootstrap/menu.py" -O "$TMP_BOOT" 2>/dev/null; then
    BOOTSTRAP_SRC="$TMP_BOOT"
  fi
fi
if [ -z "$BOOTSTRAP_SRC" ]; then
  echo "ERROR: no se pudo obtener el bootstrap (sin red / sin curl/wget)." >&2
  exit 1
fi

# 2) Checkout git del repo (clone si falta, pull si ya existe)
if [ ! -d "$TOOLS_CHECKOUT/.git" ]; then
  echo "    Clonando el repo (primera vez)..."
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$TOOLS_CHECKOUT"
else
  echo "    Checkout existente, actualizando..."
  git -C "$TOOLS_CHECKOUT" fetch origin "$BRANCH" --quiet
  git -C "$TOOLS_CHECKOUT" reset --hard "origin/$BRANCH" --quiet
fi

# 3) Bootstrap menu.py (siempre: es la fuente de verdad del mantenimiento)
cp "$BOOTSTRAP_SRC" "$NUKE_DIR/menu.py"
echo "    menu.py bootstrap instalado."
rm -f "${TMP_BOOT:-}"

echo ""
echo "==> LISTO. Reinicia Nuke."
echo "    El menu SamanTools aparecera en la barra superior."
echo "    Las actualizaciones llegan solas: aviso + boton Actualizar."