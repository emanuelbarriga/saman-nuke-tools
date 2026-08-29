"""
INSTALADOR DE SAMANTOOLS — para el Script Editor de Nuke.

COMO USAR (reinstalacion desde cero):
  1. Abre Nuke -> Script Editor (View > Script Editor o tecla W).
  2. Pega TODO este codigo y ejecuta con Ctrl+Enter.
  3. Cuando veas el mensaje de exito, reinicia Nuke.

Qué hace:
  - Si el checkout git ya existe      -> git pull (actualiza).
  - Si hay una instalacion vieja por-copia (sin .git) -> la respalda y clona limpio.
  - Si no hay nada                    -> clona por primera vez.
  - Copia el bootstrap a ~/.nuke/menu.py (el menu de mantenimiento).

Requisito: Git instalado (https://git-scm.com/downloads).
Este archivo es la fuente de verdad; el mismo codigo puede pegarse
directamente desde el README del repo.
"""

import nuke
import os
import subprocess
import shutil
import time

URL = "https://github.com/emanuelbarriga/saman-nuke-tools.git"
BRANCH = "main"
NUKE_DIR = os.path.expanduser("~/.nuke")
TOOLS = os.path.join(NUKE_DIR, "SamanTools")
MENU = os.path.join(NUKE_DIR, "menu.py")


def sh(cmd, timeout=180):
    try:
        return subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout
        ).returncode == 0
    except Exception:
        return False


def clonar_limpio():
    """Clona a un temporal y lo mueve: nunca deja checkout parcial."""
    tmp = os.path.join(os.path.dirname(TOOLS), ".saman_clone_tmp_" + time.strftime("%Y%m%d%H%M%S"))
    if not sh(["git", "clone", "--depth", "1", "--branch", BRANCH, URL, tmp]):
        shutil.rmtree(tmp, ignore_errors=True)
        return False
    shutil.rmtree(TOOLS, ignore_errors=True)
    os.rename(tmp, TOOLS)
    return True


def instalar():
    os.makedirs(NUKE_DIR, exist_ok=True)

    # 1) Checkout
    if os.path.isdir(os.path.join(TOOLS, ".git")):
        sh(["git", "-C", TOOLS, "pull", "--ff-only", "--quiet"])  # ya git: actualizar
    elif os.path.isdir(TOOLS):
        # instalacion vieja por-copia: respaldo y clon limpio
        os.rename(TOOLS, TOOLS + ".prev_" + time.strftime("%Y%m%d%H%M%S"))
        if not clonar_limpio():
            nuke.message(
                "No se pudo descargar el repositorio.\n"
                "Verificá la conexión a internet y que Git esté instalado."
            )
            return
    else:
        os.makedirs(os.path.dirname(TOOLS), exist_ok=True)
        if not clonar_limpio():
            nuke.message(
                "No se pudo descargar el repositorio.\n"
                "Verificá la conexión a internet y que Git esté instalado."
            )
            return

    # 2) Bootstrap
    bootstrap = os.path.join(TOOLS, "bootstrap", "menu.py")
    if os.path.isfile(bootstrap):
        shutil.copy2(bootstrap, MENU)
        nuke.message(
            "SamanTools instalado correctamente.\n\n"
            "Reiniciá Nuke para que aparezca el menú SamanTools."
        )
    else:
        nuke.message(
            "Instalación incompleta: no se encontró el bootstrap.\n"
            "Probá ejecutar el instalador de nuevo."
        )


instalar()