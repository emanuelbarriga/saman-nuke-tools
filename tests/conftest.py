"""
Stub de `nuke` para tests fuera de Nuke.

Los módulos de SamanTools hacen `import nuke` al tope. En pytest (fuera de
Nuke) esto falla; este fixture inyecta un stub con las piezas mínimas que
los tests usan, ANTES de importar los módulos.

Se carga automáticamente vía conftest y hace falta ejecutar pytest desde la
raíz del repo con `tests/conftest.py` en sys.path (pytest lo hace solo).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _instalar_main_falso():
    """Crea un módulo `__main__` falso con las variables PYTHON_*.

    En Nuke real, `__main__` es el módulo principal de la app y guarda
    PYTHON_TO_VFX/COMP/FROM_VFX (las escribe rutas.actualizar). Bajo pytest,
    import __main__ devolvería el módulo de pytest — no sirve. Lo reemplazamos
    por un módulo controlado para que los imports dentro de SamanTools vean
    el mismo almacén que los tests.
    """
    import types
    main_fake = types.ModuleType("__main__")
    main_fake.PYTHON_TO_VFX = ""
    main_fake.PYTHON_COMP = ""
    main_fake.PYTHON_FROM_VFX = ""
    sys.modules["__main__"] = main_fake
    return main_fake


main_fake = _instalar_main_falso()


def _instalar_stub_nuke():
    """Define un módulo `nuke` falso con las funciones que usan los módulos."""
    import types

    nuke = types.ModuleType("nuke")

    # --- nodos / knobs falsos ---
    class KnobFake:
        def __init__(self, valor=""):
            self.valor = valor
            self.script = valor
            self.visible = True

        def value(self):
            return self.valor

        def setValue(self, v):
            self.valor = v

        def setVisible(self, v):
            self.visible = v

        def toScript(self):
            return self.script

        def fromScript(self, s):
            self.script = s
            if "[python" in s.lower():
                self.valor = "RESUELTA_DINAMICA"
            else:
                self.valor = s

    class NodoFake:
        def __init__(self, cls="Read", nombre="Read1"):
            self.cls = cls
            self.nombre = nombre
            self.knobs_d = {"file": KnobFake("ruta_estatica.png")}
            self.posxy = (0, 0)
            self.selected = False

        def Class(self):
            return self.cls

        def name(self):
            return self.nombre

        def knobs(self):
            return self.knobs_d

        def __getitem__(self, k):
            return self.knobs_d.get(k, KnobFake())

        def setXYpos(self, x, y):
            self.posxy = (x, y)

        def xpos(self):
            return self.posxy[0]

        def ypos(self):
            return self.posxy[1]

        def setInput(self, idx, node):
            pass

        def inputs(self):
            return 0

        def setSelected(self, v):
            self.selected = v

    # Estado compartido de "la escena"
    estado = {
        "nodos": [],
        "seleccionados": [],
        "mensajes": [],
        "plugins": [],
        "root_name": "",
    }

    class RootFake:
        def name(self):
            return estado.get("root_name", "")

    def allNodes(cls=None):
        if cls is None:
            return list(estado["nodos"])
        return [n for n in estado["nodos"] if n.Class() == cls]

    def selectedNodes():
        return list(estado["seleccionados"])

    def thisNode():
        return estado.get("nodo_actual")

    def createNode(*a, **k):
        return NodoFake()

    def message(m):
        estado["mensajes"].append(m)

    def ask(m):
        return True

    def pluginAddPath(p, **k):
        estado["plugins"].append(p)

    def nodePaste(*a, **k):
        return NodoFake()

    # --- menú falso ---
    class MenuFake:
        def __init__(self):
            # `items` es un METODO (lo llama proyecto.cargar_scripts_proyecto a
            # traves de nuke.menu('Nodes').items()); el almacen real vive en
            # `_items` para no chocar con el nombre del metodo. Los tests
            # resetean/leen con `_items`.
            self._items = []
            self.commands = []
            self.shortcuts = []
            self.removed = []

        def items(self):
            return self._items

        def addMenu(self, name, **k):
            # Acepta kwargs (icon=...) como nuke.Menu.addMenu de Nuke 13+; los
            # tests pueden verificar el icono sin depender de esa version.
            sub = MenuFake()
            sub._nombre = name
            sub.icon = k.get("icon")
            self._items.append(sub)
            return sub

        def findItem(self, name):
            for item in self._items:
                if getattr(item, "_nombre", None) == name:
                    return item
            return None

        def addCommand(self, name, cmd, **k):
            self.commands.append((name, cmd))
            if k.get("shortcut"):
                self.shortcuts.append((name, k["shortcut"]))

        def removeItem(self, name):
            self.removed.append(name)

        def name(self):
            return getattr(self, "_nombre", "?")

    def menu(root):
        return _m if root == "Nodes" else _m

    _m = MenuFake()

    # --- helpers de OCIO/colorespace ---
    def usingOcio():
        return True

    def getOcioColorSpaces():
        return ["scene_linear (ACEScg)\tscene_linear", "Raw\traw"]

    # --- Qt para cambiar_colorspace ---
    try:
        from PySide6 import QtWidgets, QtCore
        nuke.QtWidgets = QtWidgets
        nuke.QtCore = QtCore
    except Exception:
        pass

    nuke.allNodes = allNodes
    nuke.root = lambda: RootFake()
    nuke.selectedNodes = selectedNodes
    nuke.thisNode = thisNode
    nuke.createNode = createNode
    nuke.message = message
    nuke.ask = ask
    nuke.pluginAddPath = pluginAddPath
    nuke.nodePaste = nodePaste

    # --- vista del Node Graph (nuke.center / nuke.zoom / zoomToFitSelected) ---
    def center():
        """Centro visible del DAG; nuke.center() lo devuelve como [x, y].

        Ausente en `_estado` = vista centrada en el origen (caso normal de los
        tests). Puesto a `[]` simula un centro ilegible.
        """
        if "centro_vista" in estado:
            return list(estado["centro_vista"])
        return [0, 0]

    def zoom(*a, **k):
        estado.setdefault("zoom_llamadas", [])
        if not a:
            return estado.get("zoom", 1.0)
        estado["zoom_llamadas"].append(a)
        return estado.get("zoom", 1.0)

    def zoomToFitSelected():
        estado.setdefault("zoom_to_fit", []).append(True)

    nuke.center = center
    nuke.zoom = zoom
    nuke.zoomToFitSelected = zoomToFitSelected

    # --- undo instrumentado (regresión: Undo/EndUndo desbalanceados cerraban
    # Nuke al insertar un segundo nodo de rutas). Las llamadas se registran en
    # estado["undo"] para que un test pueda exigir que NO se use.
    estado.setdefault("undo", [])

    def _undo(*a, **k):
        estado.setdefault("undo", []).append(("Undo", a))

    def _undo_name(n=None):
        estado.setdefault("undo", []).append(("Undo.name", n))

    def _undo_begin(n=None):
        estado.setdefault("undo", []).append(("Undo.begin", n))

    def _undo_end():
        estado.setdefault("undo", []).append(("Undo.end", None))

    def _end_undo():
        estado.setdefault("undo", []).append(("EndUndo", None))

    _undo.name = _undo_name
    _undo.begin = _undo_begin
    _undo.end = _undo_end
    nuke.Undo = _undo
    nuke.EndUndo = _end_undo
    nuke.beginUndo = _undo_begin
    nuke.endUndo = _undo_end
    # --- hooks de ScriptLoad: los usa rutas.aplicar_variables_desde_nodo ---
    estado["hooks_carga"] = []

    def addOnScriptLoad(funcion):
        estado["hooks_carga"].append(funcion)

    def removeOnScriptLoad(funcion):
        if funcion in estado["hooks_carga"]:
            estado["hooks_carga"].remove(funcion)

    def disparar_script_load():
        for funcion in list(estado["hooks_carga"]):
            funcion()

    nuke.addOnScriptLoad = addOnScriptLoad
    nuke.removeOnScriptLoad = removeOnScriptLoad
    nuke._disparar_script_load = disparar_script_load

    nuke.menu = menu
    nuke.usingOcio = usingOcio
    nuke.getOcioColorSpaces = getOcioColorSpaces
    nuke.NodoFake = NodoFake
    nuke.KnobFake = KnobFake
    nuke._estado = estado
    nuke.MenuFake = MenuFake

    sys.modules["nuke"] = nuke
    return nuke


nuke = _instalar_stub_nuke()