"""
menu.py — Bootstrap de artista para SamanTools (NO editar a mano).

Instalado por setup_artista.sh / setup_artista.bat en ~/.nuke/menu.py.

MODELO DE ACTUALIZACION (el artista decide, nunca se fuerza):
  1) Al arrancar Nuke solo hace 'git fetch' (barato, no modifica nada).
  2) Si hay version nueva -> alerta: "Hay una actualizacion disponible".
  3) El artista pulsa el boton del menu SamanTools > Actualizar, o acepta
     la alerta; SOLO entonces se hace 'git pull' y se aplica la version.
  4) Puede posponerlo: sigue trabajando con la version actual sin problema.
  5) La alerta se muestra como maximo 1 vez cada 6 h (no es intrusiva).

Para el mantenedor: los updates llegan a todos los artistas cuando ELLOS
eligen actualizar (y reinician Nuke). Una version nueva rota no afecta a
quienes aun no actualizaron: quedan en la version estable.

La logica de update vive AQUI (archivo estable), no en el codigo del repo:
si una version nueva rompe el menu, el boton de actualizar sigue disponible.
"""

import nuke
import os
import sys
import time
import subprocess
import traceback

# --- Configuracion: ajusta solo si cambias de cuenta/repo --------------------
REPO_URL = "https://github.com/emanuelbarriga/saman-nuke-tools.git"
BRANCH = "main"
# -----------------------------------------------------------------------------

TOOLS_DIR = os.path.expanduser("~/.nuke/SamanTools")
LOCK_FILE = os.path.join(TOOLS_DIR, ".last_update")
INTERVALO_SEG = 6 * 60 * 60  # 6 horas: frecuencia maxima de la alerta automatica


def _ejecutar_git(args, timeout=60):
    """Ejecuta git dentro de TOOLS_DIR. Devuelve (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            ["git", "-C", TOOLS_DIR] + args,
            capture_output=True,
            timeout=timeout,
        )
        return r.returncode, r.stdout, r.stderr
    except Exception:
        return -1, b"", b""


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


def _hay_git():
    return shutil_which("git") is not None


def _tiene_checkout():
    return os.path.isdir(os.path.join(TOOLS_DIR, ".git"))


def _estado_update():
    """Consulta si hay version nueva comparando HEAD local vs origin/<BRANCH>.
    Devuelve: 'ok' | 'disponible' | 'error' | 'sin_checkout' | 'sin_git'."""
    if not _hay_git():
        return "sin_git"
    if not _tiene_checkout():
        return "sin_checkout"

    rc, _, _ = _ejecutar_git(["fetch", "origin", BRANCH], timeout=60)
    if rc != 0:
        return "error"

    rc_head, out_head, _ = _ejecutar_git(["rev-parse", "HEAD"], timeout=15)
    rc_orig, out_orig, _ = _ejecutar_git(["rev-parse", "origin/" + BRANCH], timeout=15)
    if rc_head != 0 or rc_orig != 0:
        return "error"

    if out_head.strip() != out_orig.strip():
        return "disponible"
    return "ok"


def _aplicar_update():
    """Hace git pull (fast-forward) y avisa el resultado. Devuelve True si ok."""
    rc, _, err = _ejecutar_git(["pull", "--ff-only", "--quiet"], timeout=120)
    if rc == 0:
        try:
            with open(LOCK_FILE, "w"):
                pass
        except Exception:
            pass
        nuke.message(
            "SamanTools actualizado correctamente.\n\n"
            "Reiniciá Nuke para cargar la nueva versión."
        )
        return True
    nuke.message(
        "No se pudo actualizar SamanTools:\n\n%s" % err.decode(errors="replace")[:800]
    )
    return False


def _actualizar_ahora():
    """Botón manual: consulta y actualiza si hay version nueva."""
    if not _hay_git():
        nuke.message("Git no está instalado en este equipo.\nNo se puede actualizar.")
        return
    if not _tiene_checkout():
        nuke.message("SamanTools aún no está instalado.\nEjecutá setup_artista.")
        return

    estado = _estado_update()
    if estado == "ok":
        nuke.message("Ya tenés la última versión de SamanTools.")
        return
    if estado == "error":
        nuke.message("No se pudo consultar la actualización.\nVerificá tu conexión a internet.")
        return

    if nuke.ask("Hay una nueva versión de SamanTools.\n\n¿Actualizar ahora?"):
        _aplicar_update()


def _alerta_automatica():
    """Al arrancar: avisa si hay update (max. 1 vez cada 6 h). No aplica nada."""
    if not nuke.GUI:
        return
    if not _hay_git() or not _tiene_checkout():
        return

    # Rate-limit: como mucho 1 chequeo/alerta cada 6 h
    try:
        if os.path.exists(LOCK_FILE):
            if time.time() - os.path.getmtime(LOCK_FILE) < INTERVALO_SEG:
                return
    except Exception:
        pass

    estado = _estado_update()
    try:
        with open(LOCK_FILE, "w"):
            pass  # marca el chequeo pase lo que pase (evita spam)
    except Exception:
        pass

    if estado == "disponible":
        if nuke.ask(
            "Hay una nueva actualización de SamanTools disponible.\n\n"
            "¿Querés actualizar ahora?\n"
            "(Podés decir que no y seguir trabajando con la versión actual.)"
        ):
            _aplicar_update()


def _agregar_boton_menu():
    """Añade 'Actualizar SamanTools...' dentro del menú SamanTools existente.

    Se ejecuta DESPUÉS de cargar el menú real; si el menú no existe (por una
    versión rota), se crea un menú mínimo con solo el botón de actualizar,
    para que el artista siempre pueda recuperarse.
    """
    try:
        menu = nuke.menu("Nuke").findItem("SamanTools")
        if menu is None:
            menu = nuke.menu("Nuke").addMenu("SamanTools")
        menu.addCommand("Actualizar SamanTools...", _actualizar_ahora)
    except Exception:
        pass


def _clonar_si_falta():
    """Primera vez: clona el repo a TOOLS_DIR (solo si no hay checkout)."""
    if not _tiene_checkout() and _hay_git():
        try:
            os.makedirs(TOOLS_DIR, exist_ok=True)
            subprocess.run(
                ["git", "clone", "--depth", "1", "--branch", BRANCH, REPO_URL, TOOLS_DIR],
                capture_output=True,
                timeout=180,
            )
        except Exception:
            pass


def _cargar_menu_real():
    """Carga el menu.py del checkout (el código real vive en el repo)."""
    repo_menu = os.path.join(TOOLS_DIR, "menu.py")
    if os.path.isfile(repo_menu):
        try:
            with open(repo_menu, "r") as f:
                codigo = f.read()
            namespace = {"__file__": repo_menu, "__name__": "__saman_menu__"}
            exec(compile(codigo, repo_menu, "exec"), namespace)
            return True
        except Exception:
            if nuke.GUI:
                nuke.message(
                    "ATENCION: Error cargando SamanTools:\n\n%s" % traceback.format_exc()
                )
            else:
                traceback.print_exc()
    return False


def instalar():
    _clonar_si_falta()
    _cargar_menu_real()
    _agregar_boton_menu()
    _alerta_automatica()


instalar()