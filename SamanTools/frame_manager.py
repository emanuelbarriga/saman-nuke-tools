"""
FrameManagerTable - widget PySide del gizmo Breakdown.

Un QTableWidget que edita los knobs tipados del grupo (ver `breakdown_datos`:
`N`, `F_<i>`, `L_<i>`) y reconstruye el grafo interno FrameHold/Text ->
ContactSheet cuando se pulsa "Generar".

El grupo lo instancia via un knob PyCustom (tipo 52):

    addUserKnob {52 table_ui l "" -STARTLINE T __import__('frame_manager').FrameManagerKnob()}

Los botones del grupo (python_button, tipo 22) llaman a la instancia viva:

    from frame_manager import FrameManagerTable
    t = FrameManagerTable.instancia(nuke.thisNode())
    if t: t.generar()

Tres criterios de eficiencia que sostiene este modulo:

* Editar una celda escribe como maximo los dos knobs Int de esa fila; no se
  re-serializa la tabla entera (antes era un JSON completo por cada tecla).
* "Generar" reconcilia el grafo interno: reusa los FrameHold/Text que ya
  existen, crea solo los faltantes y borra solo los sobrantes.
* `resMult` del ContactSheet se crea si falta y nunca se reescribe: el valor
  elegido por el artista sobrevive a cada Generar.
"""

import weakref

import nuke

import breakdown_datos as datos

try:
    from PySide2 import QtWidgets, QtCore

    # PySide2: los enums cuelgan directo de Qt (Qt.AlignCenter, Qt.Checked).
    _ALINEACION_CENTRO = QtCore.Qt.AlignCenter
    _CHECK = QtCore.Qt.Checked
    _UNCHECK = QtCore.Qt.Unchecked
except ImportError:
    from PySide6 import QtWidgets, QtCore

    # PySide6/Nuke 14+: enums con namespace explicito.
    _ALINEACION_CENTRO = QtCore.Qt.AlignmentFlag.AlignCenter
    _CHECK = QtCore.Qt.CheckState.Checked
    _UNCHECK = QtCore.Qt.CheckState.Unchecked

# WeakValueDictionary: la instancia se libera cuando el knob cerrado deja
# de referenciarla -> sin fugas al eliminar/renombrar el nodo.
_INSTANCES = weakref.WeakValueDictionary()

#: Nodos internos que el grupo siempre conserva.
_NODOS_BASE = ("Input1", "Dot1", "ContactSheetAuto", "Crop1", "Reformat2", "Output1")

#: Separacion horizontal entre ramas generadas, en el DAG.
_PASO_X = 180

#: Color de tile del ContactSheetAuto.
_TILE_COLOR = 0xFF69F7FF


class FrameManagerTable(QtWidgets.QTableWidget):
    """Tabla editable de frames y capas, todo el componente en si mismo."""

    KEYS = list(datos.CAPAS)
    CABECERAS = ["Frame"] + [capa.capitalize() for capa in datos.CAPAS]

    def __init__(self, node):
        super(FrameManagerTable, self).__init__()
        self.node = node
        _INSTANCES[node.name()] = self

        self.setColumnCount(len(self.CABECERAS))
        self.setHorizontalHeaderLabels(self.CABECERAS)
        self.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setMinimumHeight(180)

        self.cargar_datos()
        self.cellChanged.connect(self.on_cell_changed)

    # ---------------------------------------------------------------- API

    @classmethod
    def instancia(cls, node):
        """Devuelve la instancia del widget para `node` (None si no existe)."""
        if not node:
            return None
        return _INSTANCES.get(node.name())

    def agregar(self):
        if self.rowCount() >= datos.POOL:
            nuke.message(
                "El Breakdown admite hasta %d frames." % datos.POOL
            )
            return

        row = self.rowCount()
        frame = 10
        if row > 0:
            anterior = self.item(row - 1, 0)
            if anterior is not None:
                frame = datos.normalizar_frame(anterior.text()) + 10

        self.blockSignals(True)
        try:
            self.insertRow(row)
            self._escribir_celda_frame(row, frame)
            for col_idx in range(1, len(self.KEYS) + 1):
                self.setItem(row, col_idx, self._celda_check(_UNCHECK))
        finally:
            self.blockSignals(False)

        self.selectRow(row)
        self.guardar_filas()

    def eliminar(self):
        current_row = self.currentRow()
        if current_row >= 0:
            self.removeRow(current_row)
            self.guardar_filas()

    def subir(self):
        row = self.currentRow()
        if row > 0:
            self._swap_rows(row, row - 1)
            self.selectRow(row - 1)
            self.guardar_filas()

    def bajar(self):
        row = self.currentRow()
        if 0 <= row < self.rowCount() - 1:
            self._swap_rows(row, row + 1)
            self.selectRow(row + 1)
            self.guardar_filas()

    def generar(self):
        self.guardar_filas()
        # Undo agrupado: Ctrl+Z revierte todo el cambio sin corromper el DAG.
        # Nota: esta version de Nuke no acepta un argumento de nombre en el
        # constructor de nuke.Undo(); se instancia sin argumentos.
        with nuke.Undo():
            sincronizar_grafo(self.node)

    # ------------------------------------------------------------ internos

    @staticmethod
    def _celda_check(estado):
        chk = QtWidgets.QTableWidgetItem()
        chk.setFlags(
            QtCore.Qt.ItemIsUserCheckable
            | QtCore.Qt.ItemIsEnabled
            | QtCore.Qt.ItemIsSelectable
        )
        chk.setCheckState(estado)
        return chk

    def _escribir_celda_frame(self, row, frame):
        item = QtWidgets.QTableWidgetItem(str(frame))
        item.setTextAlignment(_ALINEACION_CENTRO)
        self.setItem(row, 0, item)

    def _swap_rows(self, r1, r2):
        self.blockSignals(True)
        try:
            for col in range(self.columnCount()):
                item1 = self.takeItem(r1, col)
                item2 = self.takeItem(r2, col)
                self.setItem(r1, col, item2)
                self.setItem(r2, col, item1)
        finally:
            self.blockSignals(False)

    def _fila(self, row):
        """Una fila de la tabla como `{"frame": int, "capas": mascara}`."""
        item_frame = self.item(row, 0)
        frame = datos.normalizar_frame(item_frame.text()) if item_frame else 0

        estados = {}
        for col_idx, capa in enumerate(datos.CAPAS, start=1):
            celda = self.item(row, col_idx)
            estados[capa] = celda is not None and celda.checkState() == _CHECK
        return {"frame": frame, "capas": datos.codificar_capas(estados)}

    # ------------------------------------------------------- persistencia

    def cargar_datos(self):
        self.blockSignals(True)
        try:
            self.setRowCount(0)
            migrado = datos.migrar_legacy(self.node)
            if migrado:
                self._avisar_excedente()
            for row_idx, fila in enumerate(datos.leer_filas(self.node)):
                self.insertRow(row_idx)
                self._escribir_celda_frame(row_idx, fila["frame"])
                estados = datos.decodificar_capas(fila["capas"])
                for col_idx, capa in enumerate(datos.CAPAS, start=1):
                    estado = _CHECK if estados[capa] else _UNCHECK
                    self.setItem(row_idx, col_idx, self._celda_check(estado))
        finally:
            self.blockSignals(False)

    def _avisar_excedente(self):
        """Avisa una sola vez si el JSON legacy no entro entero en el pool."""
        excedente = datos.legacy_excedente(self.node)
        if not excedente:
            return
        nuke.message(
            "El Breakdown guardaba %d filas y la tabla admite %d. Se migraron "
            "las primeras %d y las demas quedaron intactas en el knob "
            "frame_data del nodo: nada se perdio."
            % (excedente + datos.POOL, datos.POOL, datos.POOL)
        )

    def guardar_filas(self):
        datos.escribir_filas(self.node, [self._fila(r) for r in range(self.rowCount())])

    def guardar_fila(self, row):
        if 0 <= row < self.rowCount():
            datos.escribir_fila(self.node, row + 1, self._fila(row))

    def on_cell_changed(self, row, col):
        self.guardar_fila(row)
        # Live update no destructivo: solo si se modifica la columna 'Frame'.
        if col == 0:
            self.actualizar_frame_en_vivo(row)

    def actualizar_frame_en_vivo(self, row):
        """Cambia la expresion firstFrame solo del FrameHold de esa fila.

        Operacion ultraligera: no crea ni borra nodos, y si esa rama todavia
        no se genero no hace nada.
        """
        if not (0 <= row < self.rowCount()):
            return
        frame = self._fila(row)["frame"]
        with self.node:
            fh = nuke.toNode("FrameHold_Auto_%d" % (row + 1))
            if fh:
                _expresion_si_cambia(
                    fh["firstFrame"], "%d + parent.Desfase" % frame
                )


class FrameManagerKnob(object):
    """Contenedor exigido por el knob PyCustom (addUserKnob tipo 52) de Nuke.

    Nuke instancia la clase dada en `T <expr>` y llama a `makeUI()` para
    obtener el widget. Si Nuke pasa el nombre del nodo como primer argumento
    se captura como fallback; en caso contrario se usa nuke.thisNode().
    """

    def __init__(self, *args, **kwargs):
        self._nodo = None
        if args and isinstance(args[0], str):
            try:
                self._nodo = nuke.toNode(args[0])
            except Exception:
                self._nodo = None

    def makeUI(self):
        nodo = self._nodo or nuke.thisNode()
        return FrameManagerTable(nodo)


# ------------------------------------------------- generacion del DAG


def sincronizar_grafo(nodo):
    """Reconcilia el grafo interno del grupo con las filas del storage.

    Funcion de modulo (no metodo) para poder ejercitarla sin Qt, y para que
    el contexto de grupo (`with nodo:`) resuelva los nombres relativos de
    FrameHold/Text. El llamador ya envuelve la operacion en `nuke.Undo()`.
    """
    with nodo:
        datos.migrar_legacy(nodo)
        filas = datos.leer_filas(nodo)
        total = len(filas)

        dot = nuke.toNode("Dot1")
        if dot is None:
            dot = nuke.nodes.Dot(name="Dot1")

        cs = nuke.toNode("ContactSheetAuto")
        if cs is None:
            cs = nuke.nodes.ContactSheet(name="ContactSheetAuto")

        plan = datos.plan_reconciliacion(total, _ramas_existentes())

        for indice in plan["sobrantes"]:
            _borrar_rama(indice)

        _limpiar_intrusos(nodo, set(range(1, total + 1)))
        _recortar_entradas(cs, total)

        base_x = dot.xpos() - 100
        base_y = dot.ypos() + 100
        for indice in sorted(plan["reusar"] + plan["crear"]):
            rama_x = base_x + (indice - 1) * _PASO_X
            _sincronizar_rama(indice, filas[indice - 1], dot, rama_x, base_y)

        _configurar_contactsheet(cs, total)
        _conectar_entradas(cs, total)


def _ramas_existentes():
    """Indices que ya tienen FrameHold y Text completos en el grupo."""
    indices = set()
    for indice in range(1, datos.POOL + 1):
        if nuke.toNode("FrameHold_Auto_%d" % indice) and nuke.toNode(
            "Text_Auto_%d" % indice
        ):
            indices.add(indice)
    return indices


def _borrar_rama(indice):
    for plantilla in ("FrameHold_Auto_%d", "Text_Auto_%d"):
        nodo = nuke.toNode(plantilla % indice)
        if nodo:
            nuke.delete(nodo)


# --------------------------------------------------------------- helpers
#
# Escriben un knob solo cuando el valor cambia: menos evaluaciones del DAG y
# un undo con una entrada por cambio real.


def _escribir_si_cambia(knob, valor):
    try:
        if knob.value() == valor:
            return False
    except Exception:
        pass
    knob.setValue(valor)
    return True


def _expresion_actual(knob):
    """Expresion vigente de un knob, o None si no esta animado.

    `Array_Knob` de esta version de Nuke no expone `expression()`; el script
    serializado de un knob animado es `{"<expr>"}`, asi que se lee de ahi.
    """
    try:
        if not knob.isAnimated():
            return None
        texto = knob.toScript()
    except Exception:
        return None
    if texto.startswith('{"') and texto.endswith('"}'):
        return texto[2:-2]
    return None


def _expresion_si_cambia(knob, expresion):
    if _expresion_actual(knob) == expresion:
        return False
    knob.setExpression(expresion)
    return True


def _sincronizar_rama(indice, fila, dot, xpos, ypos):
    """Crea o actualiza el par FrameHold/Text de una fila."""
    nombre_fh = "FrameHold_Auto_%d" % indice
    nombre_txt = "Text_Auto_%d" % indice

    fh = nuke.toNode(nombre_fh)
    creado = fh is None
    if creado:
        fh = nuke.nodes.FrameHold(name=nombre_fh, xpos=xpos, ypos=ypos)
    if fh.input(0) is None or fh.input(0).name() != dot.name():
        fh.setInput(0, dot)
    _expresion_si_cambia(fh["firstFrame"], "%d + parent.Desfase" % fila["frame"])

    txt = nuke.toNode(nombre_txt)
    if txt is None:
        txt = nuke.nodes.Text2(name=nombre_txt, xpos=xpos, ypos=ypos + 80)
        # La caja y la justificacion se fijan solo al crear: asi un ajuste
        # manual del artista sobre el Text existente no se pisa al regenerar.
        txt["box"].setExpression("0", 0)
        txt["box"].setExpression("0", 1)
        txt["box"].setExpression("input.width", 2)
        txt["box"].setExpression("input.height", 3)
        txt["xjustify"].setValue("left")
        txt["yjustify"].setValue("top")

    _escribir_si_cambia(txt["message"], "Frame: [value %s.firstFrame]" % nombre_fh)
    _expresion_si_cambia(txt["disable"], "!parent.VerTexto")
    if txt.input(0) is None or txt.input(0).name() != fh.name():
        txt.setInput(0, fh)


def _padre(nodo):
    """Grupo que contiene a `nodo`.

    `parent()` es la API vigente; `pparent()` existio en otras versiones. Se
    prueban las dos para no repetir el error de la version anterior, donde
    `pparent()` no existia, la excepcion se tragaba y la limpieza no borraba
    nunca nada.
    """
    for atributo in ("parent", "pparent"):
        metodo = getattr(nodo, atributo, None)
        if metodo is None:
            continue
        try:
            return metodo()
        except Exception:
            continue
    return None


def _limpiar_intrusos(grupo, deseados):
    """Borra nodos internos que no pertenecen al Breakdown.

    `nuke.allNodes()` ya esta acotado al contexto del grupo, y ademas se
    compara `_padre(nodo) is grupo`: nunca se toca un nodo del comp del
    artista, aunque comparta grupo contenedor.
    """
    permitidos = set(_NODOS_BASE)
    for indice in deseados:
        permitidos.add("FrameHold_Auto_%d" % indice)
        permitidos.add("Text_Auto_%d" % indice)

    for nodo in nuke.allNodes():
        if _padre(nodo) is not grupo:
            continue
        if nodo.name() not in permitidos:
            nuke.delete(nodo)


def _recortar_entradas(cs, total):
    """Deja el ContactSheet con exactamente `total` entradas.

    ContactSheet no tiene knob `inputs`: el numero de entradas lo fija la
    ultima conexion, asi que desconectar desde el final es lo unico que lo
    encoge. Crecer no hace falta: `setInput` agrega entradas solo.
    """
    while cs.inputs() > total:
        cs.setInput(cs.inputs() - 1, None)


def _configurar_contactsheet(cs, total):
    _escribir_si_cambia(cs["tile_color"], _TILE_COLOR)
    _escribir_si_cambia(cs["center"], True)
    _escribir_si_cambia(cs["roworder"], "TopBottom")

    if "resMult" not in cs.knobs():
        res_mult = nuke.Float_Knob("resMult", "Resolution Multiplier")
        res_mult.setRange(0.1, 2)
        cs.addKnob(res_mult)
        cs["resMult"].setValue(1.0)

    columnas, filas = datos.grilla(total)
    _escribir_si_cambia(cs["columns"], columnas)
    _escribir_si_cambia(cs["rows"], filas)
    _expresion_si_cambia(cs["width"], "input.width*columns*resMult")
    _expresion_si_cambia(cs["height"], "input.height*rows*resMult")


def _conectar_entradas(cs, total):
    """Conecta cada Text ya sincronizado a su entrada del ContactSheet."""
    for indice in range(1, total + 1):
        txt = nuke.toNode("Text_Auto_%d" % indice)
        if txt is None:
            continue
        actual = cs.input(indice - 1)
        if actual is None or actual.name() != txt.name():
            cs.setInput(indice - 1, txt)
