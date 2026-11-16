"""SamanTools.fspy — importa una cámara calibrada de fSpy y un cubo de referencia.

fSpy (https://fspy.io) resuelve la cámara de una foto a partir de puntos de fuga.
Este módulo lee el proyecto .fspy (ver `fspy_core`, puro stdlib, sin nuke) y crea:

    fSpy_cam   Camera con la solución: focal, aperturas y matriz 4x4 exacta
    fSpy_cube  Cube de referencia apoyado en el origen del mundo

El panel es un NoOp con knobs; los nodos generados van JUNTO al panel, en su
mismo contexto, nunca adentro. Nada de esto usa el NDK: es Python puro.

Flujo recomendado: elegir .fspy → Leer .fspy → Construir. Si la calibración
está mal, «Abrir en fSpy…» abre la app con el mismo archivo, se corrige ahí,
se guarda y se vuelve a apretar «Leer .fspy».
"""

import os
import subprocess
import sys
import tempfile

import nuke

from . import fspy_core

_EXTENSION = ".fspy"
_NOMBRE_PANEL = "fSpy"
_NOMBRE_CAMARA = "fSpy_cam"
_NOMBRE_CUBO = "fSpy_cube"
_NOMBRE_LECTURA = "fSpy_read"
_CALLBACK = "from SamanTools import fspy\nfspy.cb('{0}')"

# Campos de sólo lectura: (knob, etiqueta)
_CAMPOS = (
    ("r_modo", "Modo de calibración"),
    ("r_imagen", "Imagen y aspecto"),
    ("r_sensor", "Sensor (mm)"),
    ("r_focal", "Distancia focal"),
    ("r_fov", "Campo de visión H / V"),
    ("r_principal", "Punto principal"),
    ("r_fuga", "Puntos de fuga"),
    ("r_escala", "Escala"),
    ("r_referencia", "Distancia de referencia"),
)


# --------------------------------------------------------------------------- UI
def crear_o_reutilizar():
    """Inserta el panel, o enfoca el que ya exista en este contexto (máximo 1)."""
    ctx = nuke.thisGroup()
    existente = nuke.toNode(_ruta_completa(ctx, _NOMBRE_PANEL))
    if existente is not None:
        existente.showControlPanel()
        return existente
    return crear()


def crear():
    """Inserta el panel: pega nodos/fSpy.gizmo, o lo arma en Python si falta el archivo."""
    ruta = ruta_gizmo()
    if os.path.isfile(ruta):
        nuke.nodePaste(ruta)
        nodo = nuke.selectedNode()
    else:
        nodo = _nuevo(nuke.thisGroup(), "NoOp", _NOMBRE_PANEL)
        _armar_knobs(nodo)
    preparar_insercion(nodo)
    nodo.showControlPanel()
    return nodo


def ruta_gizmo():
    """Ruta del .gizmo instalado, junto a Rutas.gizmo y Breakdown.gizmo."""
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), "nodos", "fSpy.gizmo")


_VALORES_POR_DEFECTO = (
    ("crear_camara", True),
    ("crear_cubo", True),
    ("crear_read", True),
    ("tamano_cubo", 1.0),
)


def preparar_insercion(nodo):
    """Termina de configurar el nodo recién pegado: contexto y valores por defecto.

    Los booleanos se fuerzan acá porque un .gizmo NO serializa el valor cuando
    coincide con el default interno de Nuke: al pegar, la casilla vuelve a false.
    """
    nodo["ctx"].setValue(nuke.thisGroup().fullName())
    for nombre, valor in _VALORES_POR_DEFECTO:
        if nombre in nodo.knobs():
            nodo[nombre].setValue(valor)
    nodo["info"].setValue("")
    return nodo


def exportar_gizmo(destino=None):
    """Regenera nodos/fSpy.gizmo desde _armar_knobs(). Herramienta de mantenimiento.

    El .gizmo es el artefacto que se pega; _armar_knobs() es la única fuente de
    verdad del panel. Si se toca el panel, hay que volver a correr esto.
    """
    destino = destino or ruta_gizmo()
    nodo = _nuevo(nuke.root(), "NoOp", _NOMBRE_PANEL)
    _armar_knobs(nodo)
    for otro in nuke.allNodes():
        otro.setSelected(False)
    nodo.setSelected(True)
    temporal = destino + ".tmp"
    nuke.nodeCopy(temporal)
    with open(temporal) as fh:
        lineas = fh.read().splitlines(True)
    os.remove(temporal)
    desde = next(i for i, linea in enumerate(lineas) if linea.rstrip().endswith("{"))
    # newline="\n": el artefacto debe ser idéntico en macOS, Windows y Linux
    with open(destino, "w", newline="\n") as fh:
        fh.writelines(lineas[desde:])
    nuke.delete(nodo)
    return destino


def _armar_knobs(nodo):
    """Arma el panel. Separado de crear() para poder testear en batch."""
    nodo.addKnob(
        nuke.Text_Knob("hdr", "", "<b>fSpy</b> — cámara calibrada desde una foto")
    )
    nodo.addKnob(nuke.File_Knob("fspy_file", "Proyecto .fspy"))
    nodo.addKnob(_knob_oculto("ctx", "root"))
    nodo.addKnob(_boton("leer", "Leer .fspy"))
    nodo.addKnob(_boton("editar", "Abrir en fSpy…"))

    nodo.addKnob(nuke.Text_Knob("div_calibracion", "calibración", ""))
    for nombre, etiqueta in _CAMPOS:
        knob = nuke.Text_Knob(nombre, etiqueta, "—")
        knob.setEnabled(False)
        nodo.addKnob(knob)
    nodo.addKnob(nuke.Text_Knob("estado", "", "<i>Elegí un .fspy y apretá Leer.</i>"))

    nodo.addKnob(nuke.Text_Knob("div_generados", "nodos generados", ""))
    for nombre, etiqueta in (("crear_camara", "Cámara"),
                             ("crear_cubo", "Cubo de referencia en el origen")):
        casilla = nuke.Boolean_Knob(nombre, etiqueta)
        casilla.setValue(True)  # explícito: el valor del constructor no se serializa
        nodo.addKnob(casilla)
    tamano = nuke.Double_Knob("tamano_cubo", "Tamaño del cubo")
    tamano.setValue(1.0)
    tamano.setTooltip("Lado del cubo, en unidades del mundo de fSpy.")
    nodo.addKnob(tamano)
    leer_imagen = nuke.Boolean_Knob("crear_read", "Read con la imagen del proyecto")
    leer_imagen.setValue(True)
    leer_imagen.setTooltip(
        "El .fspy lleva la foto adentro: se extrae a ~/.nuke/fspy_cache y se lee "
        "desde ahí, así el Read no depende de que la imagen original siga en su lugar."
    )
    nodo.addKnob(leer_imagen)
    nodo.addKnob(_boton("construir", "Construir"))
    nodo.addKnob(_boton("borrar", "Borrar nodos generados"))
    nodo.addKnob(nuke.Text_Knob("info", "", ""))
    return nodo


def _boton(nombre, etiqueta):
    return nuke.PyScript_Knob("btn_" + nombre, etiqueta, _CALLBACK.format(nombre))


def _knob_oculto(nombre, valor):
    knob = nuke.String_Knob(nombre, "")
    knob.setValue(valor)
    knob.setVisible(False)
    return knob


# ------------------------------------------------------------------- acciones
def cb(accion):
    """Despachador de los botones. No abre diálogos: informa en el panel."""
    nodo = nuke.thisNode()
    try:
        {"leer": _leer, "editar": _editar, "construir": _construir, "borrar": _borrar}[accion](nodo)
    except Exception as exc:
        nodo["estado"].setValue(
            "<span style='color:#e06c75'><b>%s</b>: %s</span>" % (type(exc).__name__, exc)
        )
        raise


def _leer(nodo):
    """Lee el .fspy y llena los campos de sólo lectura."""
    ruta = nodo["fspy_file"].value()
    if not ruta:
        raise ValueError("no hay archivo elegido")
    cam = fspy_core.read(ruta)
    ok, esperado, obtenido = fspy_core.selftest(cam)

    nodo["r_modo"].setValue(cam["mode"])
    nodo["r_imagen"].setValue("%d x %d  (%.3f)" % (cam["width"], cam["height"], cam["aspect"]))
    nodo["r_sensor"].setValue("%.2f x %.2f" % (cam["sensor_w_mm"], cam["sensor_h_mm"]))
    nodo["r_focal"].setValue("%.2f mm   (f_rel = %.6f)" % (cam["focal_mm"], cam["f_rel"]))
    nodo["r_fov"].setValue("%.2f° / %.2f°" % (cam["fov_h_deg"], cam["fov_v_deg"]))
    nodo["r_principal"].setValue(
        "%.4f, %.4f" % cam["principal_point"]
        + ("   (centrado)" if cam["principal_point"] == (0.0, 0.0) else "")
    )
    nodo["r_fuga"].setValue(
        "  ".join("(%.4f, %.4f)" % punto for punto in cam["vanishing_points"][:2])
    )
    nodo["r_escala"].setValue("λ = %.6f" % cam["scale"])
    referencia = cam["reference_distance"]
    nodo["r_referencia"].setValue(
        ("%.4g %s" % (referencia, cam["reference_unit"]))
        if referencia
        else "no definida (escala nominal)"
    )
    if "label" in nodo.knobs():
        nodo["label"].setValue(os.path.basename(ruta))
    nodo["estado"].setValue(
        "<span style='color:%s'>Origen reproyectado: %s</span>"
        % (("#7fb069" if ok else "#e06c75"), "exacto" if ok else "no coincide")
    )
    return cam


def _editar(nodo):
    """Abre el .fspy en la app fSpy para corregir la calibración. Nunca lanza."""
    ruta = nodo["fspy_file"].value()
    if not ruta:
        raise ValueError("elegí primero un archivo .fspy")
    if not os.path.isfile(ruta):
        raise IOError("no existe el archivo:\n%s" % ruta)
    try:
        _lanzar_app(ruta)
    except Exception as exc:
        nodo["info"].setValue(
            "<span style='color:#e06c75'>no se pudo abrir fSpy: %s</span>" % exc
        )
        return False
    nodo["info"].setValue(
        "abierto en fSpy → guardá allá y apretá «Leer .fspy» para recargar"
    )
    return True


def _lanzar_app(ruta):
    """Abre el archivo con la aplicación asociada al .fspy, en cada plataforma."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", ruta])
    elif os.name == "nt":
        os.startfile(ruta)  # noqa: S606 — API estándar de Windows
    else:
        subprocess.Popen(["xdg-open", ruta])


def _construir(nodo):
    """Crea cámara y cubo junto al panel, en SU contexto (no donde esté el usuario)."""
    ctx = _contexto(nodo)
    if ctx.fullName().lower() == "root":
        return _construir_nodos(nodo, ctx)
    ctx.begin()
    try:
        return _construir_nodos(nodo, ctx)
    finally:
        ctx.end()


def _construir_nodos(nodo, ctx):
    cam = _leer(nodo)
    tamano = float(nodo["tamano_cubo"].value()) or 1.0
    hechos = []
    if nodo["crear_camara"].value():
        _camara(ctx, cam)
        hechos.append(_NOMBRE_CAMARA)
    if nodo["crear_cubo"].value():
        _cubo(ctx, tamano)
        hechos.append("%s (%g u)" % (_NOMBRE_CUBO, tamano))
    if "crear_read" in nodo.knobs() and nodo["crear_read"].value():
        ruta = _leer_imagen(ctx, cam)
        hechos.append("%s (%s)" % (_NOMBRE_LECTURA, os.path.basename(ruta)))
    nodo["info"].setValue("creado: " + (", ".join(hechos) if hechos else "nada"))
    return cam


def _borrar(nodo):
    ctx = _contexto(nodo)
    borrados = []
    for nombre in (_NOMBRE_CAMARA, _NOMBRE_CUBO, _NOMBRE_LECTURA):
        existente = nuke.toNode(_ruta_completa(ctx, nombre))
        if existente is not None:
            nuke.delete(existente)
            borrados.append(nombre)
    nodo["info"].setValue(
        "eliminado: " + (", ".join(borrados) if borrados else "no había nada")
    )


# ------------------------------------------------------------------- nodos
def _camara(ctx, cam):
    nodo = _nuevo(ctx, "Camera", _NOMBRE_CAMARA)
    nodo["haperture"].setValue(cam["sensor_w_mm"])
    nodo["vaperture"].setValue(cam["sensor_h_mm"] or cam["sensor_w_mm"] / cam["aspect"])
    nodo["focal"].setValue(cam["focal_mm"])
    # el punto principal viene en medio ancho; Nuke lo espera como fracción de ancho
    principal_u, principal_v = cam["principal_point"]
    nodo["win_translate"].setValue([principal_u / 2.0, principal_v / 2.0 / cam["aspect"]])
    distancia = max(cam["scale"], 1e-3)
    nodo["near"].setValue(distancia * 0.001)
    nodo["far"].setValue(distancia * 1000.0)
    if "useMatrix" in nodo.knobs():
        nodo["useMatrix"].setValue(True)
    nodo["matrix"].setValue(fspy_core.matrix_flat(cam))
    return nodo


def _carpeta_cache():
    """Carpeta estable para las placas extraídas. Cae a temp si ~/.nuke no se puede escribir."""
    for base in (
        os.path.join(os.path.expanduser("~"), ".nuke", "fspy_cache"),
        os.path.join(tempfile.gettempdir(), "fspy_cache"),
    ):
        try:
            os.makedirs(base, exist_ok=True)
            return base
        except OSError:
            continue
    raise IOError("no hay carpeta escribible para extraer la imagen del .fspy")


def _leer_imagen(ctx, cam):
    """Extrae la foto embebida en el .fspy y la apunta desde un Read."""
    ruta = fspy_core.extraer_imagen(cam, _carpeta_cache())
    nodo = _nuevo(ctx, "Read", _NOMBRE_LECTURA)
    nodo["file"].setValue(ruta)
    return ruta


def _cubo(ctx, tamano):
    nodo = _nuevo(ctx, "Cube", _NOMBRE_CUBO)
    nodo["scaling"].setValue([tamano, tamano, tamano], 3)
    nodo["translate"].setValue([0.0, tamano / 2.0, 0.0], 2)  # apoyado, no atravesado
    return nodo


# ------------------------------------------------------------------- contexto
def _contexto(nodo):
    """Grupo donde vive el panel. Ahí van los generados, no donde esté parado el usuario."""
    completo = (nodo["ctx"].value() if "ctx" in nodo.knobs() else "") or "root"
    if completo.lower() == "root":
        return nuke.root()
    return nuke.toNode(completo) or nuke.root()


def _ruta_completa(ctx, nombre):
    """Path completo. Node.name() da el nombre corto en 17.1; fullName() da el path."""
    completo = ctx.fullName()
    return nombre if completo.lower() == "root" else "%s.%s" % (completo, nombre)


def _nuevo(ctx, clase, nombre):
    """Crea el nodo con nombre fijo junto al panel; si ya existe, lo reemplaza."""
    existente = nuke.toNode(_ruta_completa(ctx, nombre))
    if existente is not None:
        nuke.delete(existente)
    nodo = nuke.createNode(clase, inpanel=False)
    nodo.setName(nombre)
    return nodo
