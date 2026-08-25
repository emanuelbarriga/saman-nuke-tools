"""
SamanTools.rutas - Logica del nodo Rutas movida a Python real.

El knobChanged del nodo Rutas solo hace:
    from SamanTools import rutas
    rutas.actualizar(nuke.thisNode())

Ventajas sobre el codigo embebido en el knob:
  - Legible y testeable fuera del string escapado del .gizmo/.nk
  - Reload de Reads solo cuando la ruta resuelta CAMBIO realmente
  - Se reutiliza desde el boton ActualizarProyecto
"""

import nuke
import __main__

from SamanTools import proyecto

SUFIJOS = {"MacServer": "MAC", "Windows": "WINDOWS", "Artist": "ARTIST"}


def actualizar(n=None):
    """
    Actualiza TO_VFX/COMP/FROM_VFX del proyecto activo.

    Pasos:
      1. Captura los Reads dinamicos ([python ...]) con su ruta ANTIGUA.
      2. Actualiza PYTHON_TO_VFX / PYTHON_COMP / PYTHON_FROM_VFX en __main__.
      3. Re-evalua cada Read y ejecuta reload SOLO si su ruta resuelta cambio.
      4. Actualiza la etiqueta RutaActual del nodo.
      5. Re-escanea los scripts del proyecto (SamanTools/proyecto).

    Devuelve True si cargo scripts del proyecto, False si no.
    """
    if n is None:
        n = nuke.thisNode()
    if n is None:
        return False

    usuario = n["UsuarioActivo"].value()
    sufijo = SUFIJOS.get(usuario)
    if not sufijo:
        return False

    to_vfx = n["TO_VFX_SERVER_" + sufijo].value()
    comp = n["comp_SERVER_" + sufijo].value()
    from_vfx = n["FROM_VFX_SERVER_" + sufijo].value()

    # 1) Capturar reads dinamicos ANTES de cambiar el contexto de rutas.
    reads = []
    for node in nuke.allNodes("Read"):
        if "file" not in node.knobs():
            continue
        script = node["file"].toScript()
        if "[python" in script.lower():
            reads.append((node, script, node["file"].value()))

    # 2) Actualizar variables globales usadas por las rutas relativas.
    __main__.PYTHON_TO_VFX = to_vfx
    __main__.PYTHON_COMP = comp
    __main__.PYTHON_FROM_VFX = from_vfx

    # 3) Re-evaluar y recargar SOLO si la ruta resuelta cambio realmente.
    #    Evita el reload masivo de todos los Reads del script.
    for node, script, anterior in reads:
        node["file"].fromScript(script)
        if node["file"].value() != anterior:
            node["reload"].execute()

    # 4) Etiqueta de ruta actual (mismo formato que el nodo original).
    texto_ruta = (
        "TO_VFX: {0} [PYTHON_TO_VFX]\n"
        "COMP: {1} [PYTHON_COMP]\n"
        "FROM_VFX: {2} [PYTHON_FROM_VFX]"
    ).format(to_vfx, comp, from_vfx)
    n["RutaActual"].setValue(texto_ruta)

    # 5) Re-escanear herramientas del proyecto.
    try:
        return proyecto.cargar_scripts_proyecto()
    except Exception:
        return False