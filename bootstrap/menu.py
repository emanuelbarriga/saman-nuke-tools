"""
menu.py — Bootstrap de artista para SamanTools (NO editar a mano).

Instalado por setup_artista.sh / setup_artista.bat en ~/.nuke/menu.py.

Comportamiento:
  1) Al arrancar Nuke, actualiza el checkout git local (pull silencioso).
  2) Solo descarga/actualiza como maximo 1 vez cada 6 horas, para no frenar el arranque.
  3) Si no hay red o algo falla, usa la copia local existente (nunca rompe Nuke).
  4) Carga SamanTools desde <repo>/menu.py (el codigo real vive en el repo).

Para el mantenedor: los updates llegan solos a todos los artistas al reiniciar Nuke,
sin que toquen nada. El artista SOLO hace el setup una vez con setup_artista.sh/.bat.
"""

import nuke
import os
import sys
import time
import subprocess
import traceback

# --- Configuracion: ajusta solo si cambias de cuenta/repo --------------------
REPO_URL = "https://github.com/TU_ORG/saman-nuke-tools.git"
BRANCH = "main"
# -----------------------------------------------------------------------------

TOOLS_DIR = os.path.expanduser("~/.nuke/SamanTools")
LOCK_FILE = os.path.join(TOOLS_DIR, ".last_update")
INTERVALO_SEG = 6 * 60 * 60  # 6 horas


def _git(args, timeout=45):
    """Ejecuta git dentro de TOOLS_DIR. Devuelve True si ok (o si no hay git)."""
    if not shutil_which("git"):
        return False
    try:
        r = subprocess.run(
            ["git", "-C", TOOLS_DIR] + args,
            capture_output=True,
            timeout=timeout,
        )
        return r.returncode == 0
    except Exception:
        return False


def shutil_which(cmd):
    """which() sin depender de shutil.which (compatible con todas las versiones)."""
    for base in os.environ.get("PATH", "").split(os.pathsep):
        p = os.path.join(base, cmd)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
        if sys.platform.startswith("win"):
            for ext in (".exe", ".bat", ".cmd"):
                pe = p + ext
                if os.path.isfile(pe):
                    return pe
    return None


def clone_or_update():
    """Garantiza que TOOLS_DIR sea un checkout actual del repo."""

    # 1) Si no existe checkout -> clone inicial (dentro del propio boot, sin esperar)
    if not os.path.isdir(os.path.join(TOOLS_DIR, ".git")):
        if not shutil_which("git"):
            return  # sin git: no podemos clonar, se usara lo que haya
        os.makedirs(TOOLS_DIR, exist_ok=True)
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", "--branch", BRANCH, REPO_URL, TOOLS_DIR],
                capture_output=True,
                timeout=180,
            )
        except Exception:
            pass
        return

    # 2) Rate-limit: como mucho 1 pull cada 6h
    try:
        if os.path.exists(LOCK_FILE):
            edad = time.time() - os.path.getmtime(LOCK_FILE)
            if edad < INTERVALO_SEG:
                return
    except Exception:
        pass

    # 3) Pull silencioso (fast-forward only); si falla, seguimos con lo local
    if _git(["pull", "--ff-only", "--quiet"]):
        try:
            with open(LOCK_FILE, "w"):
                pass
        except Exception:
            pass


def instalar():
    clone_or_update()

    repo_menu = os.path.join(TOOLS_DIR, "menu.py")
    if os.path.isfile(repo_menu):
        # El menu.py del repo es el que tiene la logica real (sys.path, pluginAddPath...)
        try:
            with open(repo_menu, "r") as f:
                codigo = f.read()
            # Preservamos __file__ para que el repo sepa donde esta y resuelva rutas
            namespace = {"__file__": repo_menu, "__name__": "__saman_menu__"}
            exec(compile(codigo, repo_menu, "exec"), namespace)
            return
        except Exception:
            if nuke.GUI:
                nuke.message(
                    "ATENCION: Error cargando SamanTools:\n\n%s" % traceback.format_exc()
                )
            else:
                traceback.print_exc()
    # Si no hay repo (aun), fallback minimo: buscar en ~/.nuke/SamanTools legacy
    dir_legacy = os.path.join(os.path.dirname(os.path.abspath(__file__)), "SamanTools")
    if os.path.isdir(dir_legacy) and dir_legacy not in sys.path:
        sys.path.append(dir_legacy)
        nuke.pluginAddPath(os.path.join(dir_legacy, "nodos"), addToMenuBar=False)


instalar()