"""
Tests de SamanTools.registro: registro de herramientas en la barra y en el
buscador de nodos (Tab).

El caso critico: las herramientas del buscador Tab deben registrarse con un
CALLABLE (funcion directa), NO con un string ejecutable multi-linea. Un
string con saltos de linea ('from X import y\\ny.f()') se ejecuta de forma
poco fiable dentro del buscador de nodos y puede no insertar nada al pulsar
Enter. Review y Breakdown usan callables; Rutas debe ser consistente.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import types

import pytest

import nuke
from SamanTools import registro


@pytest.fixture(autouse=True)
def _escena_limpia():
    nuke._estado["nodos"] = []
    nuke._estado["mensajes"] = []
    nuke._estado["plugins"] = []
    yield
    nuke._estado["nodos"] = []
    nuke._estado["mensajes"] = []
    nuke._estado["plugins"] = []


def _instalar(monkeypatch):
    """Ejecuta registro.instalar() neutralizando las dependencias de proyecto."""
    # Neutraliza el re-escaneo de scripts del proyecto y la inyeccion de
    # frame_manager (no queremos red/imports extra en el test).
    monkeypatch.setattr(registro.proyecto_tools, "cargar_scripts_proyecto", lambda: False)
    monkeypatch.setattr(
        registro, "_inyectar_frame_manager", lambda: None
    )
    # El stub de nuke devuelve SIEMPRE el mismo MenuFake (_m) para cualquier
    # raiz de menu; instalar() anade menus/comandos ahi.
    menu = nuke.menu("Nodes")
    menu.items[:] = []
    menu.commands[:] = []
    registro.instalar()
    return menu


def _command_de(menu_cmds, nombre):
    """Devuelve la tupla (nombre, callable/string) cuyo nombre matchee."""
    for name, cmd in menu_cmds:
        if name == nombre:
            return (name, cmd)
    return None


def test_buscador_insertar_nodo_registra_callables_no_strings(monkeypatch):
    menu = _instalar(monkeypatch)

    # En el stub, nuke.menu() devuelve SIEMPRE el mismo MenuFake para cualquier
    # raiz; el submenu del buscador TAB es 'HTLR · Saman · Samán'.
    menu_saman = next(
        (sub for sub in menu.items if getattr(sub, "_nombre", None) == "HTLR · Saman · Samán"),
        None,
    )
    assert menu_saman is not None, "Falta el submenu 'HTLR · Saman · Samán' del buscador Tab"

    insertar = next(
        (sub for sub in menu_saman.items if getattr(sub, "_nombre", None) == "Insertar Nodo"),
        None,
    )
    assert insertar is not None, "Falta el submenu 'Insertar Nodo' en el buscador Tab"

    nombres_cmd = [name for (name, _) in insertar.commands]
    assert "Rutas (Rutas VFX)" in nombres_cmd
    assert "Review (Comparación)" in nombres_cmd
    assert "Breakdown (frames por tabla)" in nombres_cmd

    for nombre in ("Rutas (Rutas VFX)", "Review (Comparación)", "Breakdown (frames por tabla)"):
        par = _command_de(insertar.commands, nombre)
        assert par is not None
        cmd = par[1]
        # Un callable (funcion) se ejecuta de forma fiable en el buscador Tab.
        # Un string con '\n' puede fallar silenciosamente: lo consideramos bug.
        assert not isinstance(cmd, str), (
            "La herramienta '%s' se registro como string en el buscador Tab. "
            "Usa la funcion directa (callable) para que Tab/Enter la ejecute." % nombre
        )
        assert callable(cmd)
