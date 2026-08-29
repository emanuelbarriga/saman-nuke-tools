"""
SamanTools.menu — Registro central de herramientas en la barra de Nuke.

Cada herramienta se añade aquí con una única llamada toolbar.addCommand().
"""

import nuke
import os
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
    """Crea el menú SamanTools en la barra superior de Nuke y registra las herramientas."""
    menu = nuke.menu("Nuke").addMenu("SamanTools")

    # --- Categoría: Utilidades ---
    sub_util = menu.addMenu("Utilidades")
    sub_util.addCommand(
        "Cambiar Espacios de Color",
        cambiar_colorspace.ejecutar_cambio_colorespace_reads,
        icon=_ruta_icono("ChangeColorSpace.svg"),
    )
    sub_util.addCommand(
        "Escanear Scripts del Proyecto",
        _escanear_scripts_proyecto,
    )

    # --- Categoría: Insertar Nodo ---
    sub_nodos = menu.addMenu("Insertar Nodo")
    sub_nodos.addCommand(
        "Rutas VFX (nodo Rutas)",
        _insertar_rutas,
    )
    sub_nodos.addCommand(
        "Review (Comparación)",
        _insertar_review,
    )
    sub_nodos.addCommand(
        "Breakdown (frames por tabla)",
        _insertar_breakdown,
    )

    # --- Información ---
    menu.addCommand(
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

    # Subcategoría dentro del buscador: Utilidades
    sub_util_nodos = menu_saman.addMenu("Utilidades")
    sub_util_nodos.addCommand(
        "ChangeColorspace (Cambiar Espacios de Color)",
        cambiar_colorspace.ejecutar_cambio_colorespace_reads,
        icon=_ruta_icono("ChangeColorSpace.svg"),
    )

    # Subcategoría dentro del buscador: Insertar Nodo
    sub_nodos_nodos = menu_saman.addMenu("Insertar Nodo")
    sub_nodos_nodos.addCommand(
        "Rutas (Rutas VFX)",
        "from SamanTools import rutas\nrutas.crear_o_reutilizar()",
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