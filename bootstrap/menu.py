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
import hashlib
import shutil
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


def _desinstalar_ahora():
    """Desinstala SamanTools: mueve checkout y bootstrap a un respaldo.

    NO borra archivos: renombra la carpeta de checkout y el menu.py con
    sufijo .desinstalado_<fecha>, para que el artista pueda recuperarlo.
    El Nuke actual sigue funcionando; el cambio se aplica al reiniciar.
    """
    if not nuke.ask(
        "¿Desinstalar SamanTools?\n\n"
        "Se quitará el menú y las herramientas globales de este equipo "
        "(los nodos ya insertados en proyectos NO se borran).\n\n"
        "Los archivos se respaldan con sufijo .desinstalado_<fecha>."
    ):
        return

    ts = time.strftime("%Y%m%d%H%M%S")
    hechos = []

    # 1) Checkout del repo
    if os.path.isdir(TOOLS_DIR):
        destino = TOOLS_DIR + ".desinstalado_" + ts
        try:
            os.rename(TOOLS_DIR, destino)
            hechos.append("Checkout movido a: %s" % destino)
        except Exception as e:
            hechos.append("No se pudo mover el checkout: %s" % e)

    # 2) menu.py bootstrap (solo si es el nuestro: contiene un marcador claro)
    boot_local = os.path.abspath(__file__)
    try:
        with open(boot_local, "r") as f:
            contenido_boot = f.read()
    except Exception:
        contenido_boot = ""
    if "SamanTools" in contenido_boot and "bootstrap de artista" in contenido_boot:
        destino_m = boot_local + ".desinstalado_" + ts
        try:
            os.rename(boot_local, destino_m)
            hechos.append("Bootstrap movido a: %s" % destino_m)
        except Exception as e:
            hechos.append("No se pudo mover el bootstrap: %s" % e)
    elif os.path.isfile(boot_local):
        hechos.append("menu.py NO se tocó (no parece ser el bootstrap de SamanTools).")

    nuke.message(
        "SamanTools desinstalado de este equipo.\n\n" + "\n".join(hechos) +
        "\n\nReiniciá Nuke para que desaparezca del menú.\n"
        "Ningún proyecto se ve afectado."
    )


def _agregar_boton_menu():
    """Añade los botones de mantenimiento dentro del menú SamanTools.

    Se ejecuta DESPUÉS de cargar el menú real; si el menú no existe (por una
    versión rota), se crea un menú mínimo con los botones de mantenimiento,
    para que el artista siempre pueda actualizar o desinstalar.
    """
    try:
        menu = nuke.menu("Nuke").findItem("SamanTools")
        if menu is None:
            menu = nuke.menu("Nuke").addMenu("SamanTools")
        menu.addCommand("Actualizar SamanTools...", _actualizar_ahora)
        menu.addCommand("Desinstalar SamanTools...", _desinstalar_ahora)
    except Exception:
        pass


def _clonar_si_falta():
    """Primera vez: clona el repo a TOOLS_DIR (solo si no hay checkout).

    Devuelve True si el checkout quedó disponible (existía o se clonó),
    False si no hay checkout y no se pudo clonar (sin git o sin red).
    """
    if _tiene_checkout():
        return True
    if not _hay_git():
        return False
    try:
        os.makedirs(TOOLS_DIR, exist_ok=True)
        r = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", BRANCH, REPO_URL, TOOLS_DIR],
            capture_output=True,
            timeout=180,
        )
        return r.returncode == 0
    except Exception:
        return False


def _checkout_completo():
    """El checkout está usable solo si existe el paquete real.

    Un clone o pull a medias deja `menu.py` pero sin `SamanTools/SamanTools/`,
    lo que produce ModuleNotFoundError al cargar. Verificamos el archivo
    clave del paquete antes de intentar nada.
    """
    return os.path.isfile(os.path.join(TOOLS_DIR, "SamanTools", "SamanTools", "registro.py"))


def _reparar_checkout():
    """Si el checkout es git pero está incompleto, lo repara con reset --hard.

    NO borra el respaldo de desinstalación: solo alinea el checkout con origin.
    Devuelve True si quedó completo.
    """
    if not _tiene_checkout() or not _hay_git():
        return False
    # Alinear con la rama remota aunque el arbol este sucio o a medias
    _ejecutar_git(["fetch", "origin", BRANCH], timeout=90)
    _ejecutar_git(["reset", "--hard", "origin/" + BRANCH], timeout=90)
    return _checkout_completo()


def _cargar_menu_real():
    """Carga el menu.py del checkout (el código real vive en el repo).

    Antes de cargar verifica que el checkout esté completo; si está a medias
    (clone/pull interrumpido) lo repara. Solo falla si no hay red ni git.
    """
    repo_menu = os.path.join(TOOLS_DIR, "menu.py")

    # Estado 'desinstalado': el checkout no existe (fue movido a respaldo por
    # Desinstalar). No es un error: el bootstrap sigue instalado y muestra
    # los botones de mantenimiento (para reinstalar), pero no debe gritar
    # un "error" cada arranque.
    if not _tiene_checkout() and not _clonar_si_falta():
        return False

    if not _checkout_completo():
        _reparar_checkout()

    if _checkout_completo() and os.path.isfile(repo_menu):
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
    elif nuke.GUI:
        nuke.message(
            "No se pudo cargar SamanTools (checkout incompleto y sin red).\n"
            "Revisá la conexión o ejecutá nuevamente el instalador."
        )
    return False


def _auto_actualizar_bootstrap():
    """Mantiene el menu.py instalado sincronizado con el bootstrap del repo.

    El menu.py bootstrap se copia a ~/.nuke SOLO al instalar; si el bootstrap
    del repo cambia (ej. nuevos botones de mantenimiento), este paso lo
    reemplaza en cada arranque. Se compara por contenido, no por fecha.
    """
    try:
        local = os.path.abspath(__file__)
        repo_boot = os.path.join(TOOLS_DIR, "bootstrap", "menu.py")
        if not os.path.isfile(repo_boot):
            return
        if os.path.abspath(repo_boot) == local:
            return

        def _hash(p):
            try:
                with open(p, "rb") as f:
                    return hashlib.md5(f.read()).hexdigest()
            except Exception:
                return None

        h_local, h_repo = _hash(local), _hash(repo_boot)
        if h_local is not None and h_repo is not None and h_local != h_repo:
            shutil.copy2(repo_boot, local)
    except Exception:
        pass


def instalar():
    _auto_actualizar_bootstrap()
    _clonar_si_falta()
    _cargar_menu_real()
    _agregar_boton_menu()
    _alerta_automatica()


instalar()