"""
SamanTools.menu — Registro central de herramientas en la barra de Nuke.

Cada herramienta se añade aquí con una única llamada toolbar.addCommand().
"""

import nuke
import os
import subprocess
import sys

from . import proyecto as proyecto_tools
from .componentes import COMPONENTES


def _componente_disponible(identificador):
    """True si un componente puede exponerse en esta instalación.

    En el checkout de desarrollo no hay manifiesto generado y se conserva el
    menú histórico completo. En un dist, COMPONENTES es el manifiesto único:
    sólo se registra una entrada si su componente fue declarado activo.
    """
    manifiesto = os.path.join(os.path.dirname(os.path.dirname(__file__)), "MANIFIESTO.md")
    if not os.path.isfile(manifiesto):
        return True
    return any(
        componente["id"] == identificador and componente["activo"]
        for componente in COMPONENTES
    )


def _ruta_icono(nombre_icono):
    """Resuelve la ruta absoluta de un icono dentro del paquete SamanTools."""
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), nombre_icono)


def _escanear_scripts_proyecto():
    """Escanea {PYTHON_COMP}/Scripts y registra los gizmos del proyecto."""
    if proyecto_tools.cargar_scripts_proyecto():
        nuke.message("Scripts del proyecto cargados correctamente.")
    else:
        nuke.message(
            "No se encontraron scripts del proyecto.\n"
            "Verifica que el nodo Rutas esté con el proyecto activo y que "
            "exista la carpeta Scripts dentro de COMP."
        )


def _insertar_rutas():
    """Crea, reutiliza o ACTUALIZA el único nodo Rutas del proyecto.

    La política vive en rutas_unico: con cero nodos pega el gizmo, con uno
    actual lo enfoca, con uno viejo lo reconstruye conservando estado y
    posición, y con dos o más fusiona y deja uno.
    """
    from SamanTools import rutas_unico

    rutas_unico.crear_o_actualizar()


def _insertar_fspy():
    """Inserta un panel fSpy nuevo (cámara calibrada desde una foto)."""
    from SamanTools import fspy

    ruta_archivo = fspy.ruta_gizmo()
    fspy.crear()
    try:
        from SamanTools import limpiar
        limpiar.sanitizar_archivo(ruta_archivo)
    except Exception:
        # Defensa idempotente y nunca lanza: el archivo puede ya estar limpio
        # (devuelve 0) o no ser legible/escribible en esta instalacion.
        pass


def _insertar_colorspaces():
    """Inserta el nodo ColorSpaces (clasifica Reads por espacio de color)."""
    ruta_archivo = os.path.join(
        os.path.dirname(os.path.realpath(__file__)), "nodos", "ColorSpaces.gizmo"
    )
    nuke.nodePaste(ruta_archivo)


def _insertar_review():
    """Inserta el nodo Review (comparación Side-by-Side) en el script actual."""
    ruta_archivo = os.path.join(os.path.dirname(os.path.realpath(__file__)), "nodos", "Review.gizmo")
    nuke.nodePaste(ruta_archivo)
    try:
        from SamanTools import limpiar
        limpiar.sanitizar_archivo(ruta_archivo)
    except Exception:
        # Defensa idempotente y nunca lanza: el archivo puede ya estar limpio
        # (devuelve 0) o no ser legible/escribible en esta instalacion.
        pass


def _limpiar_knobs_volatiles():
    """Elimina knobs volatiles de maquina del archivo en disco del comp actual.

    Suaviza el archivo serializado (.nk) con SamanTools.limpiar para que no
    viajen knobs que solo existen en esta maquina (mov64_prraw_plugin,
    render_settings_schema, monitorOutNDISenderName) y que ensucian comps
    compartidos o versionados. Nunca lanza: cualquier error se muestra con
    nuke.message.
    """
    ruta = nuke.root().name()
    if not ruta:
        nuke.message("Guardá el script primero (File > Save As) para poder limpiarlo.")
        return
    try:
        from SamanTools import limpiar
        resultado = limpiar.sanitizar_archivo(ruta)
    except Exception as e:
        nuke.message("No se pudo limpiar el archivo:\n%s\n\n%s" % (ruta, e))
        return
    if resultado == 1:
        nuke.message(
            "Se limpiaron knobs volátiles de:\n%s\n\n"
            "Recargá el script (File > Revert) para verlo." % ruta
        )
    else:
        nuke.message("El archivo no tiene knobs volátiles:\n%s" % ruta)


def _limpiar_knobs_volatiles_carpeta(_select_carpeta=None):
    """Limpia masivamente knobs volatiles de todos los .nk/.gizmo de una carpeta.

    Pide la carpeta con un QFileDialog (PySide), confirma con nuke.ask y ejecuta
    `limpiar.sanitizar_carpeta` (seguro, nunca corrompe archivos). Nunca lanza:
    cualquier error se muestra con nuke.message.

    `_select_carpeta` es un hook opcional (inyectable en tests) que devuelve la
    carpeta elegida; si no se pasa, se usa QFileDialog.getExistingDirectory.
    """
    ruta_base = ""
    try:
        if nuke.root().name():
            ruta_base = os.path.dirname(nuke.root().name())
    except Exception:
        pass
    if not ruta_base:
        try:
            import __main__
            ruta_base = getattr(__main__, "PYTHON_COMP", "") or ""
        except Exception:
            ruta_base = os.environ.get("PYTHON_COMP", "")

    if _select_carpeta is not None:
        carpeta = _select_carpeta()
    else:
        try:
            from PySide2 import QtWidgets
        except ImportError:
            try:
                from PySide6 import QtWidgets
            except ImportError:
                nuke.message("No se pudo abrir el selector de carpeta (falta PySide).")
                return
        carpeta = QtWidgets.QFileDialog.getExistingDirectory(
            None, "Seleccioná la carpeta con los .nk/.gizmo a limpiar", ruta_base
        )

    if not carpeta:
        return
    if not os.path.isdir(carpeta):
        nuke.message("La carpeta no existe:\n%s" % carpeta)
        return

    # Conteo previo (solo lectura) para el mensaje de confirmacion.
    extensiones = (".nk", ".gizmo")
    total = 0
    for raiz, directorios, archivos in os.walk(carpeta):
        directorios[:] = [d for d in directorios if not os.path.islink(os.path.join(raiz, d))]
        total += sum(
            1 for nombre in archivos if nombre.lower().endswith(extensiones)
        )
    if total == 0:
        nuke.message(
            "No se encontraron archivos .nk/.gizmo en:\n%s" % carpeta
        )
        return

    if not nuke.ask(
        "Se encontraron %d archivos .nk/.gizmo en:\n%s\n\n"
        "¿Limpiarlos? (Se eliminan líneas de knobs volátiles; se conserva todo lo demás.)"
        % (total, carpeta)
    ):
        return

    try:
        from SamanTools import limpiar
        resultado = limpiar.sanitizar_carpeta(carpeta)
    except Exception as e:
        nuke.message("No se pudo limpiar la carpeta:\n%s\n\n%s" % (carpeta, e))
        return

    limpiados = resultado.get("limpiados", 0)
    sin_cambios = resultado.get("sin_cambios", 0)
    errores = resultado.get("errores", [])

    cabecera = "Listo.\n\nLimpiados: %d\nYa estaban limpios: %d" % (limpiados, sin_cambios)
    if errores:
        lineas = [ruta for (ruta, _msg) in errores[:10]]
        extras = len(errores) - len(lineas)
        texto = cabecera + "\n\nERRORES (no se tocaron):\n" + "\n".join(lineas)
        if extras > 0:
            texto += "\n... y %d más." % extras
        nuke.message(texto)
    else:
        nuke.message(cabecera)


def _insertar_breakdown():
    """Inserta el nodo Breakdown (VFX breakdown con tabla de frames) en el script actual."""
    ruta_archivo = os.path.join(os.path.dirname(os.path.realpath(__file__)), "nodos", "Breakdown.gizmo")
    nuke.nodePaste(ruta_archivo)


def _acerca_de():
    """Muestra información del desarrollador y versión de SamanTools."""
    try:
        from . import __version__
        version = __version__
    except Exception:
        version = "desconocida"
    nuke.message(
        "SamanTools — Herramientas globales de Nuke para el estudio\n\n"
        "Versión instalada: %s\n\n"
        "Contenido: Rutas, Breakdown, Review, ColorSpaces y fSpy.\n\n"
        "Desarrollado por Emanuel Barriga — Samán Estudio\n"
        "Sitio web: https://samanestudio.com/\n"
        "Teléfono: +57 3014532504\n"
        "Correo: emanuel.barriga@samanestudio.com\n\n"
        "Repositorio: https://github.com/emanuelbarriga/saman-nuke-tools\n\n"
        "¿Encontraste un error o falta una herramienta?\n"
        "Escribime: tus datos están arriba."
        % version
    )


def _verificar_salud():
    """Muestra la salud de la instalación de SamanTools en un nuke.message.

    Es puramente local: NO hace red ni corre pytest. Reporta la versión
    instalada, el tipo de instalación (checkout git o copia) y, si es git,
    el commit y el estado del árbol de trabajo. Nunca lanza: cada parte se
    resuelve en su propio try/except.
    """
    try:
        from . import __version__
        version = __version__
    except Exception:
        version = "desconocida"

    raiz_checkout = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    es_checkout_git = os.path.isdir(os.path.join(raiz_checkout, ".git"))

    if es_checkout_git:
        try:
            r = subprocess.run(
                ["git", "-C", raiz_checkout, "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            commit = r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "desconocido"
        except Exception:
            commit = "desconocido"
        instalacion = "checkout git (commit %s)" % commit

        try:
            r = subprocess.run(
                ["git", "-C", raiz_checkout, "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode != 0:
                estado_checkout = "desconocido"
            elif r.stdout.strip():
                estado_checkout = "árbol local con cambios"
            else:
                estado_checkout = "al día"
        except Exception:
            estado_checkout = "desconocido"
    else:
        instalacion = "instalación por copia (sin git)"
        estado_checkout = "no aplica"

    try:
        nuke.message(
            "Salud de SamanTools\n\n"
            "Versión instalada: %s\n"
            "Instalación: %s\n"
            "Estado del checkout: %s" % (version, instalacion, estado_checkout)
        )
    except Exception:
        pass


def _inyectar_frame_manager():
    """
    Asegura que `frame_manager` (widget global de Breakdown) sea importable.

    El módulo vive en ~/.nuke/SamanTools/frame_manager.py (global, no por
    proyecto). Se agrega la carpeta del paquete al sys.path y se importa
    el módulo; el knob PyCustom del gizmo lo instancia con
    `T __import__('frame_manager').FrameManagerKnob()`.
    """
    try:
        ruta_paquete = os.path.dirname(os.path.realpath(__file__))
        if ruta_paquete not in sys.path:
            sys.path.append(ruta_paquete)
        import frame_manager
    except ImportError:
        # frame_manager.py ausente o con error: el knob PyCustom fallara al abrirse.
        pass


def _registrar_hooks_de_carga():
    """Engancha la politica de nodo unico de rutas a cada carga de script.

    Vive aca (y no en un init.py de la maquina) para que viaje con el repo y
    lo tenga todo artista: un .gizmo no puede garantizar la politica porque con
    cero nodos de rutas en el comp no corre nada, y el addOnScriptLoad que
    registra el motor del propio nodo solo existe en la sesion donde el nodo se
    cargo.

    No duplica el hook si se llama dos veces. Devuelve True si quedo
    enganchado.
    """
    from SamanTools import rutas_unico

    try:
        nuke.removeOnScriptLoad(rutas_unico.aplicar_politica_al_cargar)
    except Exception:
        pass

    try:
        nuke.addOnScriptLoad(rutas_unico.aplicar_politica_al_cargar)
        return True
    except Exception:
        return False


def instalar():
    """Crea el menú SamanTools en la barra superior de Nuke y registra las herramientas.

    Estructura por categorías (reestructuración aprobada): "Acerca de" queda
    directo en la raíz y las herramientas se agrupan en submenús temáticos
    (Tools, Paneles, Salud). Los comandos de mantenimiento del bootstrap
    (Actualizar/Desinstalar) se agregan DESPUÉS, sobre este mismo menú, desde
    bootstrap/menu.py. Menos niveles = menos clics.
    """
    # Antes del menu: `nuke.menu("Nuke")` no existe fuera de modo GUI, y este
    # hook tambien tiene que quedar enganchado en nuke -t (renders sin GUI).
    _registrar_hooks_de_carga()

    menu = nuke.menu("Nuke").addMenu("SamanTools")

    # v3: el menú SamanTools queda en TRES cosas. "Acerca de" es el único ítem
    # propio; "Actualizar SamanTools" (index 1) y "Desinstalar SamanTools..."
    # los agrega bootstrap/menu.py sobre este mismo menú.
    menu.addCommand("Acerca de SamanTools...", _acerca_de)

    # --- Buscador de Nodos (TAB): un solo ícono Samán con los cinco nodos ---
    # Los cinco son autocontenidos: se insertan pegando su .gizmo y no necesitan
    # ningún otro comando suelto en los menús.
    menu_nodos = nuke.menu("Nodes")
    try:
        menu_saman = menu_nodos.addMenu("Samán", icon=_ruta_icono("Saman.svg"))
    except TypeError:
        # Nuke viejo no acepta icon en addMenu: el menú funciona igual, sin ícono.
        menu_saman = menu_nodos.addMenu("Samán")

    menu_saman.addCommand(
        "Rutas (rutas VFX)",
        _insertar_rutas,
    )
    menu_saman.addCommand(
        "Breakdown (frames por tabla)",
        _insertar_breakdown,
    )
    if _componente_disponible("review"):
        menu_saman.addCommand(
            "Review (comparación)",
            _insertar_review,
        )
    if _componente_disponible("colorspaces"):
        menu_saman.addCommand(
            "ColorSpaces (espacio de color)",
            _insertar_colorspaces,
        )
    menu_saman.addCommand(
        "fSpy (cámara desde foto)",
        _insertar_fspy,
        icon=_ruta_icono("fSpy.svg"),
    )

    # Galerías del proyecto: proyecto.py las cuelga DENTRO del mismo menú Samán,
    # en un submenú con el nombre del proyecto activo.
    proyecto_tools.cargar_scripts_proyecto()

    # Inyección del widget FrameManagerTable (lo importa desde el proyecto).
    _inyectar_frame_manager()

    # --- Futuras herramientas se añaden aquí ---
    # toolbar.addCommand(
    #     "Nombre de la Herramienta",
    #     modulo.funcion_principal,
    #     icon=_ruta_icono("icono.svg"),
    # )