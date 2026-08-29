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

import os

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
    Si el nodo tiene knobs de entorno (SO_Detectado/EstadoUnidad), los
    sincroniza con valores informativos: SO detectado y estado de la unidad
    (determinado desde la primera ruta base disponible). Tolerante a knobs
    ausentes (nodos viejos o escenarios de test con solo UsuarioActivo +
    rutas).
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
        if "EstadoUnidad" in n.knobs():
            ruta_base = entorno.primera_ruta_disponible(so)
            estado = entorno.estado_unidad(ruta_base)
            n["EstadoUnidad"].setValue(_texto_estado(estado))
    except Exception:
        pass


def _recomendar_usuario(n):
    """
    Refuerza la recomendacion de usuario en nodos con seccion de entorno
    (knob UsuarioRecomendado presente):

      - Actualiza el texto informativo UsuarioRecomendado segun SO.
      - Rellena UsuarioActivo SOLO si esta vacio o NO es un valor valido
        (MacServer/Windows/Artist); NUNCA pisa un valor valido elegido a
        mano por el artista.

    En nodos viejos sin la seccion de entorno no hace nada, preservando el
    comportamiento historico de actualizar().
    """
    if "UsuarioRecomendado" not in n.knobs():
        return
    try:
        from SamanTools import entorno
    except Exception:
        return
    try:
        so = entorno.detectar_so()
        recomendado = entorno.usuario_activo(so)
        n["UsuarioRecomendado"].setValue("Usuario recomendado segun SO: " + recomendado)
        if "UsuarioActivo" in n.knobs():
            actual = str(n["UsuarioActivo"].value()).strip()
            if actual not in SUFIJOS:
                n["UsuarioActivo"].setValue(recomendado)
    except Exception:
        pass


def _aplicar_visibilidad(n, sufijo):
    """
    Muestra solo los knobs y separadores del grupo del usuario activo.

    Grupos por sufijo:
      MAC      -> TO_VFX_SERVER_MAC, comp_SERVER_MAC, FROM_VFX_SERVER_MAC, RutaMacServer
      WINDOWS  -> TO_VFX_SERVER_WINDOWS, comp_SERVER_WINDOWS, FROM_VFX_SERVER_WINDOWS, RutaWindows
      ARTIST   -> TO_VFX_SERVER_ARTIST, comp_SERVER_ARTIST, FROM_VFX_SERVER_ARTIST, RutaArtist

    Tolerancia TOTAL: si un knob no existe o no expone setVisible (nodos
    viejos, stub de tests), se saltea sin lanzar excepciones. Un nodo sin
    knobs adicionales sigue funcionando igual que antes.
    """
    grupos = {
        "MAC": [
            "TO_VFX_SERVER_MAC",
            "comp_SERVER_MAC",
            "FROM_VFX_SERVER_MAC",
            "RutaMacServer",
        ],
        "WINDOWS": [
            "TO_VFX_SERVER_WINDOWS",
            "comp_SERVER_WINDOWS",
            "FROM_VFX_SERVER_WINDOWS",
            "RutaWindows",
        ],
        "ARTIST": [
            "TO_VFX_SERVER_ARTIST",
            "comp_SERVER_ARTIST",
            "FROM_VFX_SERVER_ARTIST",
            "RutaArtist",
        ],
    }
    for suf, knobs in grupos.items():
        visible = suf == sufijo
        for nombre in knobs:
            try:
                if nombre not in n.knobs():
                    continue
                setter = getattr(n[nombre], "setVisible", None)
                if setter is not None:
                    setter(visible)
            except Exception:
                pass


def actualizar(n=None):
    """
    Actualiza TO_VFX/COMP/FROM_VFX del proyecto activo.

    Pasos:
      1. Captura los Reads dinamicos ([python ...]) con su ruta ANTIGUA.
      2. Actualiza PYTHON_TO_VFX / PYTHON_COMP / PYTHON_FROM_VFX en __main__.
      3. Re-evalua cada Read y ejecuta reload SOLO si su ruta resuelta cambio.
      4. Actualiza la etiqueta RutaActual del nodo (si aun la tiene).
      5. Re-escanea los scripts del proyecto (SamanTools/proyecto).

    Devuelve True si cargo scripts del proyecto, False si no.
    """
    if n is None:
        n = nuke.thisNode()
    if n is None:
        return False

    _recomendar_usuario(n)

    usuario = n["UsuarioActivo"].value()
    sufijo = SUFIJOS.get(usuario)
    if not sufijo:
        return False

    # Sincronizar knobs de entorno SOLO si el nodo los tiene (tolerante).
    _sincronizar_entorno(n)
    _aplicar_visibilidad(n, sufijo)

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
    #    El knob RutaActual se elimino de la version actual: solo se
    #    actualiza si el nodo aun lo tiene (nodos viejos).
    texto_ruta = (
        "TO_VFX: {0} [PYTHON_TO_VFX]\n"
        "COMP: {1} [PYTHON_COMP]\n"
        "FROM_VFX: {2} [PYTHON_FROM_VFX]"
    ).format(to_vfx, comp, from_vfx)
    if "RutaActual" in n.knobs():
        try:
            n["RutaActual"].setValue(texto_ruta)
        except Exception:
            pass

    # 5) Re-escanear herramientas del proyecto.
    try:
        return proyecto.cargar_scripts_proyecto()
    except Exception:
        return False


def refrescar_estado(n=None):
    """
    Refresca los knobs de estado del nodo Rutas: aplica la recomendacion de
    usuario (texto UsuarioRecomendado + rellena UsuarioActivo solo si esta
    vacio/invalido), muestra los knobs del grupo del usuario activo, y
    actualiza SO_Detectado, EstadoUnidad y el tile_color del nodo:

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
        _recomendar_usuario(n)

        sufijo = None
        try:
            if "UsuarioActivo" in n.knobs():
                sufijo = SUFIJOS.get(str(n["UsuarioActivo"].value()).strip())
        except Exception:
            pass
        if sufijo:
            _aplicar_visibilidad(n, sufijo)

        ruta_base = entorno.primera_ruta_disponible(so)
        estado = entorno.estado_unidad(ruta_base)
        color = 0x6aff55ff if estado["conectado"] else 0xff3b30ff

        try:
            if "SO_Detectado" in n.knobs():
                n["SO_Detectado"].setValue(so)
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


# ---------------------------------------------------------------------------
# Gestion del nodo unico Rutas (maximo UNO por proyecto)
# ---------------------------------------------------------------------------

KNOBS_VERSION_ACTUAL = frozenset(
    {
        "SeccionEntorno",
        "SO_Detectado",
        "EstadoUnidad",
        "UsuarioRecomendado",
    }
)

_KNOBS_A_MIGRAR = (
    "string",
    "UsuarioActivo",
    "TO_VFX_SERVER_MAC",
    "comp_SERVER_MAC",
    "FROM_VFX_SERVER_MAC",
    "TO_VFX_SERVER_WINDOWS",
    "comp_SERVER_WINDOWS",
    "FROM_VFX_SERVER_WINDOWS",
    "TO_VFX_SERVER_ARTIST",
    "comp_SERVER_ARTIST",
    "FROM_VFX_SERVER_ARTIST",
)


def ruta_nk_por_defecto():
    """Ruta absoluta del .nk nuevo del nodo Rutas dentro del repo."""
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "nodos",
        "Rutas.nk",
    )


def es_nodo_rutas(n):
    """
    True si el nodo es uno de Rutas, identificado por sus knobs de
    control: UsuarioActivo + los knobs de rutas de servidor. No depende
    del nombre: el artista puede renombrarlo y aun asi se detecta.

    La senal usa TO_VFX_SERVER_* (y no RutaActual, eliminado en la
    version actual) para seguir detectando nodos de TODAS las versiones:
    los viejo (con RutaActual), los intermedios y los nuevos.

    Tolerante a None y a nodos raros.
    """
    if n is None:
        return False
    try:
        knobs = n.knobs()
    except Exception:
        return False
    if "UsuarioActivo" not in knobs:
        return False
    return any(
        s in knobs
        for s in ("TO_VFX_SERVER_MAC", "TO_VFX_SERVER_WINDOWS", "TO_VFX_SERVER_ARTIST")
    )


def encontrar_nodos_rutas():
    """Lista de todos los nodos Rutas presentes en el script actual."""
    try:
        todos = nuke.allNodes()
    except Exception:
        return []
    return [n for n in todos if es_nodo_rutas(n)]


def es_version_actual(n):
    """
    True si el nodo tiene TODOS los knobs de la version actual del nodo
    (seccion de entorno informativo: Entorno/SO_Detectado/EstadoUnidad/
    UsuarioRecomendado). Un nodo viejo no los tiene.
    """
    if n is None:
        return False
    try:
        knobs = n.knobs()
    except Exception:
        return False
    return KNOBS_VERSION_ACTUAL.issubset(knobs)


def _seleccionar(n):
    """
    Deja a `n` como unica seleccion: limpia la seleccion actual y selecciona
    el nodo. Totalmente tolerante: si algo no existe o no expone setSelected,
    se saltea sin lanzar.
    """
    try:
        for nodo in nuke.allNodes():
            setter = getattr(nodo, "setSelected", None)
            if setter is not None:
                setter(False)
    except Exception:
        pass
    if n is None:
        return
    try:
        setter = getattr(n, "setSelected", None)
        if setter is not None:
            setter(True)
    except Exception:
        pass


def _enfocar_nodo(n):
    """
    Lleva al artista hasta el nodo Rutas existente: lo deja como unica
    seleccion, centra el Node Graph en el (nuke.zoomToFitSelected) y abre
    sus propiedades (showControlPanel). Es la UX de "pulsar el atajo y el
    nodo aparece enfrente con su panel abierto".

    Totalmente tolerante: si algo no existe (stub de tests, Nuke sin GUI,
    nodo sin panel), se saltea sin lanzar excepciones.
    """
    _seleccionar(n)
    try:
        if hasattr(nuke, "zoomToFitSelected"):
            nuke.zoomToFitSelected()
    except Exception:
        pass
    if n is not None:
        try:
            abrir = getattr(n, "showControlPanel", None)
            if abrir is not None:
                abrir()
        except Exception:
            pass


def _reconstruir_nodo(n, ruta_nk):
    """
    Reconstruye un nodo Rutas viejo con el .nk nuevo: copia los valores del
    nodo existente, lo borra, pega el .nk, y restaura valores + posicion.

    Se conservan: proyecto (string), UsuarioActivo y las 9 rutas de servidor.
    NOTA: si el nodo estaba cableado a otros nodos, hay que reconectarlo a
    mano (el nodo nuevo no conserva los inputs).

    Devuelve el nodo nuevo o None si algo fallo en el camino.
    """
    valores = {}
    try:
        for nombre in _KNOBS_A_MIGRAR:
            if nombre in n.knobs():
                knob = n[nombre]
                if knob is not None and hasattr(knob, "value"):
                    valores[nombre] = knob.value()
    except Exception:
        pass

    posicion = None
    try:
        posicion = (n.xpos(), n.ypos())
    except Exception:
        posicion = None

    abrio_undo = False
    try:
        nuke.Undo()
        abrio_undo = True
    except Exception:
        pass

    try:
        try:
            nuke.delete(n)
        except Exception:
            pass

        nuevo = nuke.nodePaste(ruta_nk)
        if nuevo is None:
            return None

        for nombre, valor in valores.items():
            try:
                if nombre in nuevo.knobs():
                    knob = nuevo[nombre]
                    if knob is not None and hasattr(knob, "setValue"):
                        knob.setValue(valor)
            except Exception:
                pass

        if posicion is not None and hasattr(nuevo, "setXYpos"):
            try:
                nuevo.setXYpos(posicion[0], posicion[1])
            except Exception:
                pass

        try:
            refrescar_estado(nuevo)
        except Exception:
            pass
        try:
            actualizar(nuevo)
        except Exception:
            pass
        return nuevo
    finally:
        if abrio_undo:
            try:
                nuke.EndUndo()
            except Exception:
                pass


def crear_o_reutilizar(ruta_nk=None):
    """
    Punto unico de creacion del nodo Rutas (lo usan el menu SamanTools y el
    buscador TAB). Garantiza MAXIMO UN nodo Rutas por proyecto:

      - 0 nodos: pega el .nk nuevo y refresca su estado.
      - 1 nodo  version actual: avisa que ya existe y lo selecciona.
      - 1 nodo  version anterior: ofrece reconstruirlo (conservando
        proyecto/rutas/usuario/posicion); si el usuario niega, no toca nada.
      - >1 nodos: avisa la cantidad y selecciona el primero (no borra nada).

    Devuelve el nodo Rutas resultante o None.
    """
    if ruta_nk is None:
        ruta_nk = ruta_nk_por_defecto()

    nodos = encontrar_nodos_rutas()

    if not nodos:
        try:
            nuevo = nuke.nodePaste(ruta_nk)
        except Exception:
            return None
        if nuevo is not None:
            try:
                refrescar_estado(nuevo)
            except Exception:
                pass
        return nuevo

    if len(nodos) == 1:
        n = nodos[0]
        if es_version_actual(n):
            _enfocar_nodo(n)
            return n

        actualizar = nuke.ask(
            "Hay un nodo Rutas de una version anterior.\n\n"
            "¿Actualizarlo ahora?\n"
            "Se conservan proyecto, rutas, usuario y posicion.\n"
            "Si estaba cableado a otros nodos, habra que reconectarlo."
        )
        if actualizar:
            return _reconstruir_nodo(n, ruta_nk)
        nuke.message("No se actualizó el nodo Rutas: se conserva la version anterior.")
        _enfocar_nodo(n)
        return n

    nuke.message(
        "Hay {0} nodos Rutas en este proyecto (se admite maximo 1).\n"
        "No se borró nada: revisalos a mano y deja solo uno.".format(len(nodos))
    )
    _enfocar_nodo(nodos[0])
    return nodos[0]


def avisar_duplicados(n=None):
    """
    Si hay mas de 1 nodo Rutas en el script, muestra un aviso informativo.
    Pensado para llamarse desde el knobChanged del nodo al cargar/crear
    (thisKnob() es None). Tolerante: nunca lanza.
    """
    if n is not None:
        try:
            if not es_nodo_rutas(n):
                return
        except Exception:
            return
    try:
        cantidad = len(encontrar_nodos_rutas())
    except Exception:
        return
    if cantidad > 1:
        try:
            nuke.message(
                "Se detectaron {0} nodos Rutas en este script "
                "(se admite maximo 1 por proyecto).\n"
                "Revisalos a mano y borra los que sobren.".format(cantidad)
            )
        except Exception:
            pass