"""
SamanTools.proyecto - Carga dinamica de herramientas por proyecto.

Cada proyecto guarda sus herramientas (gizmos/nk) en:
    {PYTHON_COMP}/Scripts/

Disponibilidad: si la ruta no existe (LucidLink desmontado o proyecto
inactivo), no se registra nada -> las herramientas solo aparecen
cuando el proyecto esta conectado.
"""

import nuke
import os

SUBMENU = "HTLR · Saman · Samán · Galerías"
EXTENSIONES = (".gizmo", ".nk")


def _get_comp():
    """Devuelve PYTHON_COMP guardado por el nodo Rutas en __main__."""
    import __main__
    return getattr(__main__, "PYTHON_COMP", "") or os.environ.get("PYTHON_COMP", "")


def obtener_ruta_scripts():
    """Devuelve la ruta {PYTHON_COMP}/Scripts o None si no existe."""
    comp = _get_comp()
    if not comp:
        return None
    ruta = os.path.join(comp, "Scripts")
    return ruta if os.path.isdir(ruta) else None


def _nombre_proyecto():
    """Lee el knob 'Proyecto' del nodo Rutas del script actual, si existe."""
    for n in nuke.allNodes():
        if "UsuarioActivo" in n.knobs() and "RutaActual" in n.knobs():
            if "string" in n.knobs():
                p = n["string"].value().strip()
                if p:
                    return p
    return "Proyecto"


def actualizar_desde_nodo_rutas(n=None):
    """
    Lee usuario/rutas del nodo Rutas, actualiza PYTHON_* en __main__
    y re-escanea los scripts del proyecto.

    Es la version explicita para el boton Actualizar: no depende de que
    el knobChanged se dispare al hacer setValue con el mismo valor.
    """
    from SamanTools import rutas
    return rutas.actualizar(n)


def _escanear(ruta):
    """Escanea recursivamente .gizmo/.nk; devuelve [(nombre_nodo, etiqueta_menu)]."""
    resultados = []
    for curr_dir, _sub_dirs, archivos in os.walk(ruta):
        rel = os.path.relpath(curr_dir, ruta)
        for archivo in sorted(archivos):
            if archivo.lower().endswith(EXTENSIONES):
                nombre = os.path.splitext(archivo)[0]
                if rel == ".":
                    etiqueta = nombre
                else:
                    etiqueta = "/".join(rel.split(os.sep) + [nombre])
                resultados.append((nombre, etiqueta))
    return resultados


# Palabras que clasifican un gizmo del proyecto como "galería de assets/compra".
# 'muzzle' solo califica cuando es galeria (muzzle_flashes_*), no MuzzleHTLR (herramienta).
PALABRAS_GALERIA = (
    "blood", "bullet", "electrical", "gun", "muzzle_flashes",
    "sparks", "splatter", "flash", "smoke",
)


def _clasificar(nombre):
    """Devuelve la subcategoria del gizmo: 'Galerías' o 'Herramientas'."""
    n = nombre.lower()
    if any(p in n for p in PALABRAS_GALERIA):
        return "Galerías"
    return "Herramientas"



def cargar_scripts_proyecto():
    """
    Escanea {PYTHON_COMP}/Scripts y registra cada gizmo en el menu
    Nodes (buscable con Tab) bajo el nombre del proyecto.

    SIEMPRE limpia el submenu anterior primero: si el proyecto no tiene
    scripts (o la ruta no existe), el submenu desaparece en lugar de
    quedar colgado con las herramientas del proyecto previo.

    Devuelve True si cargo algo, False si no hay ruta/herramientas.
    """
    ruta = obtener_ruta_scripts()
    menu_nodos = nuke.menu("Nodes")

    # Siempre eliminar el submenu anterior, haya o no ruta disponible.
    if SUBMENU in [item.name() for item in menu_nodos.items()]:
        menu_nodos.removeItem(SUBMENU)

    if not ruta:
        # Sin Lucid / sin proyecto activo: submenu ya limpio, nada que cargar.
        return False

    nuke.pluginAddPath(ruta)

    herramientas = _escanear(ruta)
    if not herramientas:
        # La carpeta existe pero no tiene .gizmo/.nk: nada que registrar.
        return False

    submenu = menu_nodos.addMenu(SUBMENU)

    # Agrupa los gizmos en subcategorias dentro del submenu del proyecto:
    # 'Galerías' (assets de compra) y 'Herramientas' (Breakdown, Review, etc.).
    por_categoria = {"Galerías": [], "Herramientas": []}
    for nombre_nodo, etiqueta in herramientas:
        por_categoria.setdefault(_clasificar(nombre_nodo), []).append(
            (nombre_nodo, etiqueta)
        )

    # Orden: Herramientas primero, luego Galerías.
    for categoria in ("Herramientas", "Galerías"):
        items = por_categoria.get(categoria)
        if not items:
            continue
        sub = submenu.addMenu(categoria)
        for nombre_nodo, etiqueta in items:
            sub.addCommand(
                etiqueta,
                "nuke.createNode('{}')".format(nombre_nodo),
            )
    return True