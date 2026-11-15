"""Pruebas del contrato de knobs del nodo Breakdown (S4, S5, S6 y S8)."""

import json
import re
import sys
import types

from SamanTools import breakdown_datos as datos

GIZMO = "SamanTools/nodos/Breakdown.gizmo"


class _Knob(object):
    """Doble de un knob que registra las escrituras recibidas."""

    def __init__(self, valor=0):
        self._valor = valor
        self.escrituras = 0

    def value(self):
        return self._valor

    def setValue(self, valor):
        self._valor = valor
        self.escrituras += 1


class _Nodo(object):
    """Doble del nodo con el pool tipado completo."""

    def __init__(self, **knobs):
        self._knobs = {nombre: _Knob(valor) for nombre, valor in knobs.items()}

    def knobs(self):
        return self._knobs

    def __getitem__(self, nombre):
        return self._knobs[nombre]


def _nodo(**sobrescritos):
    """Crea un nodo con tres filas tipadas equivalentes al ejemplo legacy."""
    knobs = {
        datos.KNOB_FILAS: 3,
        datos.KNOB_LEGACY: "",
        datos.KNOB_VERSION: datos.VERSION_DATOS,
    }
    for indice in range(1, datos.POOL + 1):
        knobs[datos.knob_frame(indice)] = 0
        knobs[datos.knob_capas(indice)] = 0
    knobs["F_1"], knobs["F_2"], knobs["F_3"] = 10, 20, 30
    knobs["L_2"], knobs["L_3"] = 1, 2
    knobs.update(sobrescritos)
    return _Nodo(**knobs)


def _escrituras(nodo):
    """Devuelve los nombres de knobs que recibieron una escritura."""
    return [nombre for nombre, knob in nodo.knobs().items() if knob.escrituras]


# ------------------------------------------------------------------ S4


def test_el_pool_del_modulo_coincide_con_el_del_gizmo():
    """S4: el gizmo declara exactamente el pool que usa el módulo."""
    with open(GIZMO) as archivo:
        gizmo = archivo.read()
    frames = [int(indice) for indice in re.findall(r"addUserKnob \{3 F_(\d+) ", gizmo)]
    capas = [int(indice) for indice in re.findall(r"addUserKnob \{3 L_(\d+) ", gizmo)]

    assert frames == list(range(1, datos.POOL + 1))
    assert capas == list(range(1, datos.POOL + 1))
    assert "addUserKnob {3 N " in gizmo


def test_el_gizmo_declara_el_marcador_de_version_sin_default():
    """S17: `datos_ver` no puede tener valor serializado.

    Si el `.gizmo` shipea `datos_ver 2`, un comp del gizmo original arranca
    creyendose migrado y sus filas nunca se vuelcan. En cambio `N`/`F_<i>` si
    llevan defaults: asi un nodo nuevo muestra las filas de ejemplo (un comp
    viejo con la tabla vacia lo normaliza la migracion, no la ausencia de
    defaults).

    El regex tolera la indentacion porque en el `.gizmo` todas las lineas
    van con un espacio adelante.
    """
    with open(GIZMO) as archivo:
        gizmo = archivo.read()

    assert "addUserKnob {3 datos_ver " in gizmo
    assert re.search(r"^\s*datos_ver\s+\S", gizmo, re.M) is None


def test_el_gizmo_declara_la_pestana_columnas_y_sus_knobs():
    """S13/S15: pestana Columnas, 8 slots de nombre/tipo y el knob TXT."""
    with open(GIZMO) as archivo:
        gizmo = archivo.read()

    assert "addUserKnob {20 Columnas l Columnas}" in gizmo
    assert "addUserKnob {3 Cantidad " in gizmo
    assert "addUserKnob {1 TXT " in gizmo
    for slot in range(1, datos.MAX_COLUMNAS + 1):
        assert "addUserKnob {1 Col_%d_nombre " % slot in gizmo
        assert "addUserKnob {4 Col_%d_tipo " % slot in gizmo
    assert "aplicar_columnas" in gizmo


def test_escribir_filas_nunca_pide_knobs_fuera_del_pool():
    """S4: un contador corrupto no lleva la limpieza fuera del pool."""
    nodo = _nodo(N=datos.POOL + 100)

    datos.escribir_filas(nodo, [{"frame": 5, "capas": 1}])

    assert nodo["N"].value() == 1
    assert datos.leer_filas(nodo) == [{"frame": 5, "capas": 1}]


# ------------------------------------------------------------------ S5


def test_editar_una_celda_escribe_solo_los_knobs_de_su_fila():
    """S5: editar un frame no reescribe contador, JSON ni otra fila."""
    nodo = _nodo()
    for knob in nodo.knobs().values():
        knob.escrituras = 0

    datos.escribir_fila(nodo, 2, {"frame": 25, "capas": 1})

    assert _escrituras(nodo) == [datos.knob_frame(2)]
    assert nodo[datos.KNOB_FILAS].value() == 3
    assert nodo[datos.KNOB_LEGACY].value() == ""


def test_editar_una_celda_sin_cambios_no_escribe_nada():
    """S5: una edición sin diferencia evita entradas de undo innecesarias."""
    nodo = _nodo()
    for knob in nodo.knobs().values():
        knob.escrituras = 0

    datos.escribir_fila(nodo, 1, {"frame": 10, "capas": 0})

    assert _escrituras(nodo) == []


# ------------------------------------------------------------------ S6


class _NodoNuke(object):
    """Doble mínimo de nodo Nuke para probar la limpieza del grupo."""

    def __init__(self, nombre, padre):
        self._nombre = nombre
        self._padre = padre

    def name(self):
        return self._nombre

    def pparent(self):
        return self._padre


def _frame_manager_con_nuke(monkeypatch, grupo, nodos):
    """Importa frame_manager con Nuke y PySide2 simulados."""
    borrados = []

    class _Base(object):
        def __init__(self, *args, **kwargs):
            pass

    qt = types.SimpleNamespace(
        Qt=types.SimpleNamespace(
            AlignCenter="c",
            Checked="on",
            Unchecked="off",
            ItemIsUserCheckable=1,
            ItemIsEnabled=2,
            ItemIsSelectable=4,
        )
    )
    pyside = types.ModuleType("PySide2")
    pyside.QtWidgets = types.SimpleNamespace(
        QTableWidget=_Base,
        QTableWidgetItem=_Base,
        QHeaderView=types.SimpleNamespace(Stretch=1),
        QAbstractItemView=types.SimpleNamespace(SelectRows=1, SingleSelection=1),
    )
    pyside.QtCore = types.SimpleNamespace(Qt=qt.Qt)
    pyside.Qt = qt.Qt
    nuke = types.ModuleType("nuke")
    nuke.allNodes = lambda: list(nodos)
    nuke.thisNode = lambda: grupo
    nuke.delete = lambda nodo: borrados.append(nodo.name())
    nuke.message = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "PySide2", pyside)
    monkeypatch.setitem(sys.modules, "nuke", nuke)
    monkeypatch.delitem(sys.modules, "frame_manager", raising=False)
    sys.path.insert(0, "SamanTools")
    try:
        import frame_manager
    finally:
        sys.path.pop(0)
    return frame_manager, borrados


def test_limpiar_intrusos_no_borra_nodos_de_otro_comp(monkeypatch):
    """S6: la limpieza se limita al grupo Breakdown actual."""
    grupo = _NodoNuke("Breakdown1", None)
    raiz = _NodoNuke("Root", None)
    merge_artista = _NodoNuke("Merge1", raiz)
    huerfano = _NodoNuke("FrameHold_Auto_1", raiz)
    interno_malo = _NodoNuke("Grade1", grupo)
    interno_permitido = _NodoNuke("ContactSheetAuto", grupo)
    frame_manager, borrados = _frame_manager_con_nuke(
        monkeypatch,
        grupo,
        [merge_artista, huerfano, interno_malo, interno_permitido],
    )

    frame_manager._limpiar_intrusos(grupo, {1})

    assert borrados == ["Grade1"]
    assert "Merge1" not in borrados
    assert "FrameHold_Auto_1" not in borrados


def test_los_nodos_fijos_del_gizmo_figuran_en_la_lista_blanca():
    """S6: la lista blanca conserva todos los nodos fijos del gizmo."""
    with open(GIZMO) as archivo:
        gizmo = archivo.read()
    with open("SamanTools/frame_manager.py") as archivo:
        frame_manager = archivo.read()

    coincidencia = re.search(r"_NODOS_BASE = \(([^)]*)\)", frame_manager)
    lista_blanca = set(re.findall(r'"(\w+)"', coincidencia.group(1)))
    fijos = set(re.findall(r"^\s+name (\w+)", gizmo, re.M)) - {"Breakdown"}
    fijos = {
        nombre
        for nombre in fijos
        if not nombre.startswith(("FrameHold_Auto_", "Text_Auto_"))
    }

    assert fijos == lista_blanca


# ------------------------------------------------------------------ S8


def _legacy(filas):
    """Serializa filas legacy con las cinco capas fijas."""
    return json.dumps(
        [
            {
                "frame": frame,
                "brillo": brillo,
                "muzzle": muzzle,
                "humo": humo,
                "impacto": impacto,
                "sangre": sangre,
            }
            for frame, brillo, muzzle, humo, impacto, sangre in filas
        ]
    )


def test_migrar_legacy_con_excedente_conserva_el_json_como_respaldo():
    """S8: las ocho filas fuera del pool quedan recuperables en el legacy."""
    filas = [
        (indice * 10, True, False, False, False, False)
        for indice in range(1, 41)
    ]
    texto_legacy = _legacy(filas)
    nodo = _nodo(**{datos.KNOB_LEGACY: texto_legacy, datos.KNOB_VERSION: 0})

    assert datos.migrar_legacy(nodo) is True
    assert len(datos.leer_filas(nodo)) == datos.POOL
    assert nodo[datos.KNOB_LEGACY].value() == texto_legacy
    assert datos.legacy_excedente(nodo) == 8
