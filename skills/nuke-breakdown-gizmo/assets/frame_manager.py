"""
FrameManagerTable - Widget PySide optimizado para el gizmo Breakdown/Review.

Un QTableWidget que edita el knob `frame_data` del grupo (JSON con frames y
capas visuales Brillo/Muzzle/Humo/Impacto/Sangre) y reconstruye el grafo
interno FrameHold/Text -> ContactSheet cuando se pulsa "Generar".

El grupo lo instancia via un knob PyCustom (tipo 52):
    addUserKnob {52 table_ui l "" -STARTLINE T __import__('frame_manager').FrameManagerKnob()}

Los botones del grupo (python_button, tipo 22) llaman a la instancia viva
con: FrameManagerTable.instancia(nuke.thisNode()).metodo()
"""

import json
import weakref
import math
import nuke

try:
    from PySide2 import QtWidgets, QtCore
    # PySide2: los enums cuelgan directo de Qt (Qt.AlignCenter, Qt.Checked).
    QtAlign = QtCore.Qt
    QtCheck = QtCore.Qt
except ImportError:
    from PySide6 import QtWidgets, QtCore
    # PySide6/Nuke 14+: enums con namespace explicito.
    QtAlign = QtCore.Qt.AlignmentFlag
    QtCheck = QtCore.Qt.CheckState

# WeakValueDictionary: la instancia se libera cuando el knob cerrado deja
# de referenciarla -> sin fugas al eliminar/renombrar el nodo.
_INSTANCES = weakref.WeakValueDictionary()


class FrameManagerTable(QtWidgets.QTableWidget):
    """Tabla editable de frames y capas, todo el componente en si mismo."""

    KEYS = ["brillo", "muzzle", "humo", "impacto", "sangre"]
    CABECERAS = ["Frame", "Brillo", "Muzzle", "Humo", "Impacto", "Sangre"]

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
        row = self.rowCount()
        last_frame = 10
        if row > 0:
            try:
                last_frame = int(self.item(row - 1, 0).text()) + 10
            except (ValueError, AttributeError):
                pass

        self.blockSignals(True)
        try:
            self.insertRow(row)
            item_frame = QtWidgets.QTableWidgetItem(str(last_frame))
            item_frame.setTextAlignment(QtAlign.AlignCenter)
            self.setItem(row, 0, item_frame)

            for col_idx in range(1, len(self.KEYS) + 1):
                self.setItem(row, col_idx, self._celda_check(QtCheck.Unchecked))
        finally:
            self.blockSignals(False)

        self.selectRow(row)
        self.guardar_datos()

    def eliminar(self):
        current_row = self.currentRow()
        if current_row >= 0:
            self.removeRow(current_row)
            self.guardar_datos()

    def subir(self):
        row = self.currentRow()
        if row > 0:
            self._swap_rows(row, row - 1)
            self.selectRow(row - 1)
            self.guardar_datos()

    def bajar(self):
        row = self.currentRow()
        if 0 <= row < self.rowCount() - 1:
            self._swap_rows(row, row + 1)
            self.selectRow(row + 1)
            self.guardar_datos()

    def generar(self):
        self.guardar_datos()
        data_str = self.node["frame_data"].value()
        try:
            items = json.loads(data_str)
        except Exception:
            items = []

        # Undo agrupado: Ctrl+Z revierte todo el cambio sin corromper el DAG.
        # Nota: esta version de Nuke no acepta un argumento de nombre en el
        # constructor de nuke.Undo(); se instancia sin argumentos.
        with nuke.Undo():
            with self.node:
                keep = ["Input1", "Dot1", "ContactSheetAuto", "Crop1", "Reformat2", "Output1"]
                for n in nuke.allNodes():
                    if n.name() not in keep:
                        nuke.delete(n)

                dot = nuke.toNode("Dot1")
                cs = nuke.toNode("ContactSheetAuto")
                if not cs:
                    cs = nuke.nodes.ContactSheet(name="ContactSheetAuto")

                self._configurar_contactsheet(cs, len(items))

                for idx in range(cs.inputs()):
                    cs.setInput(idx, None)

                # Posicion visible en el DAG, partiendo del Dot.
                start_x = dot.xpos() - 100
                start_y = dot.ypos() + 100

                for i, item in enumerate(items, 1):
                    frame_num = item.get("frame", 1)
                    offset_x = (i - 1) * 180

                    fh = nuke.nodes.FrameHold(
                        name="FrameHold_Auto_%d" % i,
                        xpos=start_x + offset_x,
                        ypos=start_y,
                    )
                    fh.setInput(0, dot)
                    fh["firstFrame"].setExpression("%d + parent.Desfase" % frame_num)

                    txt = nuke.nodes.Text2(
                        name="Text_Auto_%d" % i,
                        xpos=start_x + offset_x,
                        ypos=start_y + 80,
                    )
                    txt.setInput(0, fh)
                    txt["message"].setValue("Frame: [value FrameHold_Auto_%d.firstFrame]" % i)
                    txt["disable"].setExpression("!parent.VerTexto")
                    txt["box"].setExpression("0", 0)
                    txt["box"].setExpression("0", 1)
                    txt["box"].setExpression("input.width", 2)
                    txt["box"].setExpression("input.height", 3)
                    txt["xjustify"].setValue("left")
                    txt["yjustify"].setValue("top")

                    cs.setInput(i - 1, txt)

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

    def _configurar_contactsheet(self, cs, n_inputs):
        cs["tile_color"].setValue(int(0xFF69F7FF))
        cs["center"].setValue(True)
        cs["roworder"].setValue("TopBottom")

        if "inputs" in cs.knobs():
            cs["inputs"].setValue(n_inputs)
        if "resMult" not in cs.knobs():
            k = nuke.Float_Knob("resMult", "Resolution Multiplier")
            k.setRange(0.1, 2)
            cs.addKnob(k)
        cs["resMult"].setValue(1.0)

        # Cuadricula calculada en Python (elimina las expresiones TCL sqrt/ceil).
        if n_inputs > 0:
            cols = math.ceil(math.sqrt(n_inputs))
            rows = math.ceil(n_inputs / float(cols))
        else:
            cols, rows = 1, 1

        cs["columns"].setValue(cols)
        cs["rows"].setValue(rows)
        cs["width"].setExpression("input.width*columns*resMult")
        cs["height"].setExpression("input.height*rows*resMult")

    # ----------------------------------------------------------- persistencia

    def cargar_datos(self):
        self.blockSignals(True)
        try:
            self.setRowCount(0)
            data_str = (
                self.node["frame_data"].value()
                if "frame_data" in self.node.knobs()
                else "[]"
            )
            try:
                data = json.loads(data_str)
            except Exception:
                data = []

            for row_idx, item in enumerate(data):
                self.insertRow(row_idx)
                item_frame = QtWidgets.QTableWidgetItem(str(item.get("frame", 0)))
                item_frame.setTextAlignment(QtAlign.AlignCenter)
                self.setItem(row_idx, 0, item_frame)

                for col_idx, key in enumerate(self.KEYS, start=1):
                    estado = (
                        QtCheck.Checked if item.get(key, False) else QtCheck.Unchecked
                    )
                    self.setItem(row_idx, col_idx, self._celda_check(estado))
        finally:
            self.blockSignals(False)

    def guardar_datos(self):
        data = []
        for row in range(self.rowCount()):
            frame_item = self.item(row, 0)
            try:
                frame_val = int(frame_item.text()) if frame_item else 0
            except ValueError:
                frame_val = 0

            row_data = {"frame": frame_val}
            for col_idx, key in enumerate(self.KEYS, start=1):
                item = self.item(row, col_idx)
                row_data[key] = (
                    item.checkState() == QtCheck.Checked if item else False
                )
            data.append(row_data)

        if "frame_data" in self.node.knobs():
            self.node["frame_data"].setValue(json.dumps(data))

    def on_cell_changed(self, row, col):
        self.guardar_datos()
        # Live update no destructivo: solo si se modifica la columna 'Frame'.
        if col == 0:
            self.actualizar_frames_en_vivo()

    def actualizar_frames_en_vivo(self):
        """Actualiza en tiempo real solo los FrameHolds que ya existen en el grupo.

        Operacion ultraligera: cambia la expresion firstFrame sin borrar ni
        crear nodos. Si aun no se genero nada (nuke.toNode devuelve None),
        falla en silencio y no toca el DAG.
        """
        data_str = (
            self.node["frame_data"].value()
            if "frame_data" in self.node.knobs()
            else "[]"
        )
        try:
            items = json.loads(data_str)
        except Exception:
            return

        with self.node:
            for i, item in enumerate(items, 1):
                frame_num = item.get("frame", 1)
                fh = nuke.toNode("FrameHold_Auto_%d" % i)
                if fh:
                    fh["firstFrame"].setExpression("%d + parent.Desfase" % frame_num)


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
