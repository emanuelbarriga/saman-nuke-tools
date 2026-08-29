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
            self.items = []
            self.commands = []
            self.removed = []

        def items(self):
            return self.items

        def addMenu(self, name):
            sub = MenuFake()
            sub._nombre = name
            self.items.append(sub)
            return sub

        def addCommand(self, name, cmd, **k):
            self.commands.append((name, cmd))

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