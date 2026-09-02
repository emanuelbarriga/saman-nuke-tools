"""
SamanTools.menu — Registro central de herramientas en la barra de Nuke.

Cada herramienta se añade aquí con una única llamada toolbar.addCommand().
"""

import nuke
import os
import subprocess
import sys

from . import cambiar_colorspace
from . import proyecto as proyecto_tools


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
    """Inserta el nodo Rutas (rutas VFX dinámicas) en el script actual."""
    from SamanTools import rutas

    rutas.crear_o_reutilizar()


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
        "Contenido: Breakdown, Review, Rutas y utilidades de producción.\n\n"
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


def instalar():
    """Crea el menú SamanTools en la barra superior de Nuke y registra las herramientas.

    Estructura plana (reestructuración aprobada): las herramientas van
    DIRECTAS en el menú SamanTools y solo queda el submenú "Configuración"
    para el mantenimiento. Menos niveles = menos clics.
    """
    menu = nuke.menu("Nuke").addMenu("SamanTools")

    # --- Herramientas directas (menú plano) ---
    menu.addCommand(
        "Cambiar ColorSpace...",
        cambiar_colorspace.ejecutar_cambio_colorespace_reads,
        icon=_ruta_icono("ChangeColorSpace.svg"),
    )
    menu.addCommand(
        "Breakdown",
        _insertar_breakdown,
    )
    # Comando lazy (string): el módulo panel_comentarios solo se importa al
    # hacer clic, para no romper la carga del menú si PySide no está o no hay GUI.
    # Atajo Ctrl+Alt+C: abre la pestaña de comentarios desde cualquier lado.
    menu.addCommand(
        "Panel de Comentarios",
        "from SamanTools import panel_comentarios\npanel_comentarios.abrir_panel()",
        shortcut="Ctrl+Alt+C",
    )
    # Comando lazy (string): diagnostico_red no se importa al tope para no
    # cargar urllib al arrancar; se importa solo al hacer clic.
    menu.addCommand(
        "Diagnóstico de Red",
        "from SamanTools import diagnostico_red\ndiagnostico_red.ejecutar()",
    )

    # Separador visual entre categorías (Nuke lo dibuja como línea).
    menu.addMenu("-")

    # --- Categoría: Configuración ---
    # Los comandos de mantenimiento del bootstrap (Actualizar/Desinstalar) se
    # agregan DESPUÉS, sobre este mismo submenú, desde bootstrap/menu.py.
    sub_configuracion = menu.addMenu("Configuración")
    sub_configuracion.addCommand(
        "Verificar Salud del Plugin...",
        _verificar_salud,
    )
    sub_configuracion.addCommand(
        "Escanear Scripts del Proyecto",
        _escanear_scripts_proyecto,
    )
    sub_configuracion.addCommand(
        "Limpiar knobs volátiles",
        _limpiar_knobs_volatiles,
    )
    sub_configuracion.addCommand(
        "Limpiar knobs volátiles en carpeta...",
        _limpiar_knobs_volatiles_carpeta,
    )
    sub_configuracion.addCommand(
        "Acerca de SamanTools...",
        _acerca_de,
    )

    # Carga automatica si el proyecto ya esta disponible al arrancar.
    proyecto_tools.cargar_scripts_proyecto()

    # --- Registro en el buscador de Nodos (Tab) ---
    # Un .gizmo con raiz NoOp no se indexa solo en el buscador;
    # registrarlo en el menu Nodes lo hace buscable con Tab.
    # El nombre del submenu contiene los alias del proyecto (HTLR/Saman/Saman)
    # para que escribir cualquiera de ellos en el buscador muestre las herramientas.
    # NOTA: proyecto.py usa el submenu "HTLR · Saman · Samán · Galerías" (con
    # removeItem propio) para las herramientas dinamicas del proyecto; este submenu
    # "HTLR · Saman · Samán" es para las herramientas FIJAS y no debe borrarse.
    menu_nodos = nuke.menu("Nodes")
    menu_saman = menu_nodos.addMenu("HTLR · Saman · Samán")

    # Subcategoría dentro del buscador: Insertar Nodo
    sub_nodos_nodos = menu_saman.addMenu("Insertar Nodo")
    sub_nodos_nodos.addCommand(
        "Rutas (Rutas VFX)",
        _insertar_rutas,
    )
    sub_nodos_nodos.addCommand(
        "Review (Comparación)",
        _insertar_review,
    )
    sub_nodos_nodos.addCommand(
        "Breakdown (frames por tabla)",
        _insertar_breakdown,
    )

    # Inyección del widget FrameManagerTable (lo importa desde el proyecto).
    _inyectar_frame_manager()

    # --- Futuras herramientas se añaden aquí ---
    # toolbar.addCommand(
    #     "Nombre de la Herramienta",
    #     modulo.funcion_principal,
    #     icon=_ruta_icono("icono.svg"),
    # )