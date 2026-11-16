"""Pruebas de aislamiento entre paneles fSpy en el mismo contexto."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import nuke
from SamanTools import fspy
from SamanTools import registro


class _Knob:
    def __init__(self, valor=""):
        self.valor = valor

    def value(self):
        return self.valor

    def setValue(self, valor, *args):
        self.valor = valor


class _Nodo:
    def __init__(self, clase, nombre):
        self.clase = clase
        self.nombre = nombre
        self.knobs_d = {}

    def name(self):
        return self.nombre

    def setName(self, nombre):
        self.nombre = nombre

    def fullName(self):
        return self.nombre

    def knobs(self):
        return self.knobs_d

    def __getitem__(self, nombre):
        return self.knobs_d.setdefault(nombre, _Knob())

    def showControlPanel(self):
        pass


@pytest.fixture
def escena_fspy(monkeypatch):
    nodos = []
    root = _Nodo("Root", "root")

    def crear_nodo(clase, **kwargs):
        nodo = _Nodo(clase, "%s%d" % (clase, len(nodos) + 1))
        nodos.append(nodo)
        return nodo

    def buscar(nombre):
        return next((nodo for nodo in nodos if nodo.name() == nombre), None)

    def borrar(nodo):
        nodos.remove(nodo)

    monkeypatch.setattr(nuke, "createNode", crear_nodo)
    monkeypatch.setattr(nuke, "toNode", buscar, raising=False)
    monkeypatch.setattr(nuke, "delete", borrar, raising=False)
    monkeypatch.setattr(nuke, "root", lambda: root)
    monkeypatch.setattr(nuke, "thisGroup", lambda: root, raising=False)
    monkeypatch.setattr(fspy, "_leer", lambda nodo: {
        "sensor_w_mm": 36.0,
        "sensor_h_mm": 24.0,
        "focal_mm": 50.0,
        "principal_point": (0.0, 0.0),
        "aspect": 1.5,
        "scale": 1.0,
    })
    monkeypatch.setattr(fspy.fspy_core, "matrix_flat", lambda cam: [1.0] * 16)
    monkeypatch.setattr(fspy.fspy_core, "extraer_imagen", lambda cam, carpeta: "/tmp/fspy.png")
    monkeypatch.setattr(fspy, "_carpeta_cache", lambda: "/tmp")

    def panel(nombre):
        nodo = _Nodo("NoOp", nombre)
        nodo.knobs_d = {
            "ctx": _Knob("root"),
            "tamano_cubo": _Knob(1.0),
            "crear_camara": _Knob(True),
            "crear_cubo": _Knob(True),
            "crear_read": _Knob(True),
            "info": _Knob(),
        }
        return nodo

    return nodos, root, panel


def test_primer_panel_conserva_los_nombres_historicos(escena_fspy):
    nodos, root, panel = escena_fspy

    fspy._construir_nodos(panel("fSpy"), root)

    assert [nodo.name() for nodo in nodos] == ["fSpy_cam", "fSpy_cube", "fSpy_read"]


def test_segundo_panel_usa_su_propio_prefijo(escena_fspy):
    nodos, root, panel = escena_fspy

    fspy._construir_nodos(panel("fSpy1"), root)

    assert [nodo.name() for nodo in nodos] == ["fSpy1_cam", "fSpy1_cube", "fSpy1_read"]


def test_construir_segundo_panel_no_sobrescribe_artefactos_del_primero(escena_fspy):
    nodos, root, panel = escena_fspy
    primero = panel("fSpy")
    segundo = panel("fSpy1")

    fspy._construir_nodos(primero, root)
    artefactos_primero = list(nodos)
    fspy._construir_nodos(segundo, root)

    assert all(nodo in nodos for nodo in artefactos_primero)
    assert [nodo.name() for nodo in nodos] == [
        "fSpy_cam", "fSpy_cube", "fSpy_read",
        "fSpy1_cam", "fSpy1_cube", "fSpy1_read",
    ]
    assert "fSpy1_cam" in segundo["info"].value()


def test_borrar_solo_elimina_los_artefactos_del_panel_que_lo_invoca(escena_fspy):
    nodos, root, panel = escena_fspy
    primero = panel("fSpy")
    segundo = panel("fSpy1")
    fspy._construir_nodos(primero, root)
    fspy._construir_nodos(segundo, root)

    fspy._borrar(segundo)

    assert [nodo.name() for nodo in nodos] == ["fSpy_cam", "fSpy_cube", "fSpy_read"]
    assert segundo["info"].value() == "eliminado: fSpy1_cam, fSpy1_cube, fSpy1_read"


def test_insertar_fspy_crea_un_panel_aunque_ya_exista(monkeypatch):
    creados = []
    monkeypatch.setattr(fspy, "ruta_gizmo", lambda: "/tmp/fSpy.gizmo")
    monkeypatch.setattr(fspy, "crear", lambda: creados.append(object()))
    monkeypatch.setattr(registro, "limpiar", None, raising=False)

    registro._insertar_fspy()
    registro._insertar_fspy()

    assert len(creados) == 2
