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


def _version_instalada():
    """Devuelve (version, commit) del checkout instalado en TOOLS_DIR.

    - version: __version__ de SamanTools/__init__.py (SemVer del repo).
    - commit: hash corto de HEAD — la señal fiel de qué código está cargado
      (la version SemVer solo cambia en releases formales; el commit cambia
      con cada push).
    Nunca lanza excepciones; ante cualquier fallo devuelve desconocido.
    """
    version = "desconocida"
    try:
        import importlib.util
        ruta_init = os.path.join(TOOLS_DIR, "SamanTools", "__init__.py")
        spec = importlib.util.spec_from_file_location("saman_tools_version", ruta_init)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        version = getattr(mod, "__version__", "desconocida")
    except Exception:
        pass

    rc, out, _ = _ejecutar_git(["rev-parse", "--short", "HEAD"], timeout=15)
    commit = out.decode(errors="replace").strip() if rc == 0 else "?"
    return version, commit


def _aplicar_update():
    """Hace git pull (fast-forward) y avisa el resultado. Devuelve True si ok."""
    rc, _, err = _ejecutar_git(["pull", "--ff-only", "--quiet"], timeout=120)
    if rc == 0:
        try:
            with open(LOCK_FILE, "w"):
                pass
        except Exception:
            pass
        version, commit = _version_instalada()
        nuke.message(
            "SamanTools actualizado correctamente.\n\n"
            "Versión: %s\n"
            "Commit: %s\n\n"
            "Reiniciá Nuke para cargar la nueva versión." % (version, commit)
        )
        return True
    nuke.message(
        "No se pudo actualizar SamanTools:\n\n%s" % err.decode(errors="replace")[:800]
    )
    return False


def _actualizar_ahora():
    """Botón manual: instalación o actualización, según el estado.

    - Sin checkout: instala (clone limpio desde GitHub).
    - Con checkout: consulta y actualiza si hay version nueva.
    """
    if not _hay_git():
        nuke.message("Git no está instalado en este equipo.\nNo se puede instalar.")
        return

    if not _tiene_checkout():
        if nuke.ask(
            "SamanTools no está instalado en este equipo.\n\n"
            "¿Querés instalarlo ahora (descargando desde GitHub)?"
        ):
            if _clonar_si_falta():
                _auto_actualizar_bootstrap()
                nuke.message(
                    "SamanTools instalado correctamente.\n\n"
                    "Reiniciá Nuke para que aparezca el menú."
                )
            else:
                nuke.message(
                    "No se pudo instalar SamanTools.\n"
                    "Verificá la conexión a internet e intentá de nuevo."
                )
        return

    estado = _estado_update()
    if estado == "ok":
        version, commit = _version_instalada()
        nuke.message(
            "Ya tenés la última versión de SamanTools.\n\n"
            "Versión: %s\n"
            "Commit: %s\n\n"
            "Tu copia instalada está al día con GitHub." % (version, commit)
        )
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
    """Desinstala SamanTools de forma definitiva: BORRA (no respalda).

    Elimina:
      - el checkout ~/.nuke/SamanTools y cualquier respaldo .desinstalado_*,
      - el bootstrap ~/.nuke/menu.py (si es el nuestro).
    Los nodos ya insertados en proyectos NO se borran (pero el widget global
    del Breakdown dejará de estar disponible en equipos sin el paquete).
    """
    if not nuke.ask(
        "¿Desinstalar SamanTools?\n\n"
        "Se BORRARÁN todos los archivos de SamanTools de este equipo:\n"
        "  - ~/.nuke/SamanTools (herramientas + respaldos)\n"
        "  - ~/.nuke/menu.py (bootstrap)\n\n"
        "Los nodos ya insertados en proyectos NO se borran.\n\n"
        "¿Confirmás?"
    ):
        return

    padre = os.path.dirname(TOOLS_DIR)
    nombre = os.path.basename(TOOLS_DIR)
    hechos = []

    # 1) Checkout + respaldos de desinstalación (basura de ciclos previos)
    try:
        for item in os.listdir(padre):
            if item == nombre or item.startswith(nombre + ".desinstalado_"):
                ruta = os.path.join(padre, item)
                shutil.rmtree(ruta, ignore_errors=True)
                hechos.append("Eliminado: %s" % item)
    except Exception as e:
        hechos.append("No se pudo limpiar la carpeta: %s" % e)

    # 2) menu.py bootstrap (solo si es el nuestro: contiene un marcador claro)
    boot_local = os.path.abspath(__file__)
    try:
        with open(boot_local, "r") as f:
            contenido_boot = f.read()
    except Exception:
        contenido_boot = ""
    if "SamanTools" in contenido_boot and "bootstrap de artista" in contenido_boot.lower():
        try:
            os.remove(boot_local)
            hechos.append("Eliminado: %s" % os.path.basename(boot_local))
        except Exception as e:
            hechos.append("No se pudo borrar el bootstrap: %s" % e)
    elif os.path.isfile(boot_local):
        hechos.append("menu.py NO se tocó (no parece ser el bootstrap de SamanTools).")

    nuke.message(
        "SamanTools desinstalado de este equipo.\n\n" + "\n".join(hechos) +
        "\n\nNo queda ningún archivo de SamanTools. Reiniciá Nuke."
    )


def _agregar_boton_menu():
    """Añade los botones de mantenimiento SOLO si hay un checkout.

    Regla: sin SamanTools instalado NO se crea ningún menú. El menú
    SamanTools (con Actualizar/Desinstalar) aparece únicamente cuando el
    checkout existe — instalado o en estado de reparación. Así el estado
    'desinstalado' deja el menú completamente limpio.
    """
    if not _tiene_checkout():
        return  # desinstalado: sin menú de SamanTools
    try:
        menu = nuke.menu("Nuke").findItem("SamanTools")
        if menu is None:
            menu = nuke.menu("Nuke").addMenu("SamanTools")
        sub = menu.findItem("Configuración")
        if sub is None:
            sub = menu.addMenu("Configuración")
        sub.addCommand("Actualizar SamanTools...", _actualizar_ahora)
        sub.addCommand("Desinstalar SamanTools...", _desinstalar_ahora)
    except Exception:
        pass


def _clonar_si_falta():
    """Clona el repo a TOOLS_DIR usando un directorio temporal y rename.

    Nunca deja un checkout parcial: si el clone falla (sin red), el temporal
    se borra y TOOLS_DIR queda sin tocar. Devuelve True si quedó disponible.

    IMPORTANTE: esto NO se ejecuta en el arranque (evita el ciclo de intentos
    fallidos sin red). Solo lo llaman el botón Actualizar o el instalador.
    """
    if _tiene_checkout():
        return True
    if not _hay_git():
        return False
    padre = os.path.dirname(TOOLS_DIR)
    os.makedirs(padre, exist_ok=True)
    tmp = os.path.join(padre, ".saman_clone_tmp_" + time.strftime("%Y%m%d%H%M%S"))
    try:
        r = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", BRANCH, REPO_URL, tmp],
            capture_output=True,
            timeout=180,
        )
        if r.returncode != 0:
            shutil.rmtree(tmp, ignore_errors=True)
            return False
        shutil.rmtree(TOOLS_DIR, ignore_errors=True)   # elimina cualquier resto
        os.rename(tmp, TOOLS_DIR)
        return True
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        return False


def _checkout_completo():
    """El checkout está usable solo si existe el paquete real.

    TOOLS_DIR ya ES el checkout del repo (~/.nuke/SamanTools); dentro vive
    la carpeta `SamanTools/` con `registro.py`. Un clone o pull a medias
    deja `menu.py` pero sin `SamanTools/registro.py`, lo que produce
    ModuleNotFoundError al cargar. Verificamos el archivo clave del paquete
    antes de intentar nada.
    """
    return os.path.isfile(os.path.join(TOOLS_DIR, "SamanTools", "registro.py"))


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

    Regla: si no hay checkout (desinstalado / nunca instalado / sin red),
    NO intenta clonar y NO muestra error — silencio total. En ese estado el
    bootstrap solo deja los botones de mantenimiento (Actualizar re-instala,
    Desinstalar confirma/borra). Si hay checkout pero está incompleto, lo
    repara silenciosamente.
    """
    if not _tiene_checkout():
        return False  # desinstalado o nunca instalado: silencio

    repo_menu = os.path.join(TOOLS_DIR, "menu.py")

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
    # NO se clona en el arranque: si no hay checkout (desinstalado / sin red),
    # el bootstrap queda en silencio con solo los botones de mantenimiento.
    # La instalacion la hace el boton Actualizar o el instalador de setup.
    _cargar_menu_real()
    _agregar_boton_menu()
    _alerta_automatica()


instalar()