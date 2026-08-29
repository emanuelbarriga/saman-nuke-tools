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

# Guarda antireentrada de refrescar_estado: evita un loop infinito si un
# setValue dentro de knobChanged vuelve a disparar knobChanged.
_refrescando = False


def _texto_estado(estado):
    """Texto legible para el knob EstadoUnidad a partir del dict de estado."""
    base = "Conectado" if estado.get("conectado") else "Desconectado"
    detalle = estado.get("detalle") or ""
    return (base + " - " + detalle) if detalle else base


def _sincronizar_entorno(n):
    """
    Si el nodo tiene knobs de entorno (SO_Detectado/RutaBase/EstadoUnidad),
    los sincroniza: SO detectado, ruta base detectada por defecto si esta
    vacia, y estado de la unidad. Tolerante a knobs ausentes (nodos viejos
    o escenarios de test con solo UsuarioActivo + rutas).
    """
    try:
        from SamanTools import entorno
    except Exception:
        return

    so = entorno.detectar_so()
    try:
        if "SO_Detectado" in n.knobs():
            n["SO_Detectado"].setValue(so)
    except Exception:
        pass

    try:
        if "RutaBase" in n.knobs():
            ruta_base = n["RutaBase"].value()
            ruta_base = ruta_base.strip() if ruta_base else ""
            if not ruta_base:
                detectada = entorno.primera_ruta_disponible(so)
                if detectada:
                    n["RutaBase"].setValue(detectada)
                    ruta_base = detectada
            if "EstadoUnidad" in n.knobs():
                estado = entorno.estado_unidad(ruta_base)
                n["EstadoUnidad"].setValue(_texto_estado(estado))
    except Exception:
        pass


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

    # Sincronizar knobs de entorno SOLO si el nodo los tiene (tolerante).
    _sincronizar_entorno(n)

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


def refrescar_estado(n=None):
    """
    Refresca los knobs de estado del nodo Rutas: SO_Detectado, RutaBase
    (rellena la detectada por defecto si esta vacia), EstadoUnidad y el
    tile_color del nodo:

        verde 0x6aff55ff -> unidad conectada
        rojo  0xff3b30ff -> unidad desconectada

    Solo toca knobs que existan; nunca lanza excepciones si falta algo.
    Devuelve True si pudo evaluar el estado, False si no.
    """
    global _refrescando
    if _refrescando:
        return False
    if n is None:
        n = nuke.thisNode()
    if n is None:
        return False

    _refrescando = True
    try:
        from SamanTools import entorno

        so = entorno.detectar_so()
        ruta_base = None
        try:
            if "RutaBase" in n.knobs():
                ruta_base = n["RutaBase"].value()
                ruta_base = ruta_base.strip() if ruta_base else ""
        except Exception:
            pass
        if not ruta_base:
            ruta_base = entorno.primera_ruta_disponible(so)

        estado = entorno.estado_unidad(ruta_base)
        color = 0x6aff55ff if estado["conectado"] else 0xff3b30ff

        try:
            if "SO_Detectado" in n.knobs():
                n["SO_Detectado"].setValue(so)
        except Exception:
            pass
        try:
            if "RutaBase" in n.knobs():
                n["RutaBase"].setValue(ruta_base or "")
        except Exception:
            pass
        try:
            if "EstadoUnidad" in n.knobs():
                n["EstadoUnidad"].setValue(_texto_estado(estado))
        except Exception:
            pass
        try:
            if "tile_color" in n.knobs():
                n["tile_color"].setValue(color)
        except Exception:
            pass
        return True
    finally:
        _refrescando = False