"""
Tests del menú superior SamanTools y del buscador de Nodos (Tab).

Cubre la reestructuración aprobada: el menú superior se organiza por
categorías con "Acerca de" directo en la raíz y submenús temáticos
v3: el menú SamanTools queda en tres cosas (Acerca de + Actualizar + Desinstalar
que agrega el bootstrap) y el buscador TAB expone un único menú Samán con los
cinco nodos.
(Rutas / Review / Breakdown) — sin Utilidades.
"""

import os
import subprocess
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    monkeypatch.setattr(registro.proyecto_tools, "cargar_scripts_proyecto", lambda: False)
    monkeypatch.setattr(registro, "_inyectar_frame_manager", lambda: None)
    # El stub de nuke devuelve SIEMPRE el mismo MenuFake (_m) para cualquier
    # raiz de menu; instalar() anade menus/comandos ahi.
    menu = nuke.menu("Nodes")
    menu._items[:] = []
    menu.commands[:] = []
    registro.instalar()
    return menu


def _submenu_de(menu, nombre):
    return next(
        (sub for sub in menu._items if getattr(sub, "_nombre", None) == nombre),
        None,
    )


def _nombres_comandos(submenu):
    return [name for (name, _) in submenu.commands]


def test_instalar_crea_estructura_nueva(monkeypatch):
    menu = _instalar(monkeypatch)

    # v3: el menu SamanTools tiene TRES cosas. "Acerca de" es el unico item
    # propio; "Actualizar SamanTools" y "Desinstalar SamanTools..." los agrega
    # bootstrap/menu.py sobre este mismo menu.
    saman = _submenu_de(menu, "SamanTools")
    assert saman is not None, "Falta el submenu 'SamanTools'"
    assert _nombres_comandos(saman) == ["Acerca de SamanTools..."]
    assert [getattr(sub, "_nombre", None) for sub in saman.items()] == []


def test_el_buscador_tab_expone_un_solo_icono_saman_con_los_cinco_nodos(monkeypatch):
    menu = _instalar(monkeypatch)

    submenus = [getattr(sub, "_nombre", None) for sub in menu.items()]
    assert submenus.count("Samán") == 1
    assert "HTLR · Saman · Samán" not in submenus
    assert "Insertar Nodo" not in submenus
    assert "Salud" not in submenus
    assert "Tools" not in submenus

    saman = _submenu_de(menu, "Samán")
    assert saman is not None, "Falta el submenu 'Samán' del buscador Tab"
    assert saman.icon and saman.icon.endswith("Saman.svg"), (
        "el menu Saman debe llevar el icono del estudio"
    )
    assert _nombres_comandos(saman) == [
        "Rutas (rutas VFX)",
        "Breakdown (frames por tabla)",
        "Review (comparación)",
        "ColorSpaces (espacio de color)",
        "fSpy (cámara desde foto)",
    ]


def test_ningun_nodo_se_registra_fuera_del_menu_saman(monkeypatch):
    menu = _instalar(monkeypatch)
    saman = _submenu_de(menu, "Samán")

    def _comandos_recursivos(sub):
        for name, _cmd in sub.commands:
            yield name
        for hijo in sub.items():
            for name in _comandos_recursivos(hijo):
                yield name

    fuera = set(_comandos_recursivos(menu)) - set(_comandos_recursivos(saman))
    assert not any("ChangeColorspace" in name for name in fuera)
    for nombre in (
        "Rutas (rutas VFX)",
        "Breakdown (frames por tabla)",
        "Review (comparación)",
        "ColorSpaces (espacio de color)",
        "fSpy (cámara desde foto)",
    ):
        assert nombre not in fuera, "el nodo se registra solo dentro de Saman"


def test_verificar_salud_mensaje(monkeypatch):
    mensajes = []
    monkeypatch.setattr(nuke, "message", mensajes.append)

    # Fuerza el camino 'checkout git' aunque el paquete este copiado sin .git.
    original_isdir = os.path.isdir

    def _isdir_git(p):
        if p.endswith(".git"):
            return True
        return original_isdir(p)

    monkeypatch.setattr(os.path, "isdir", _isdir_git)

    def _git_fake(args, **kwargs):
        if "rev-parse" in args:
            return types.SimpleNamespace(returncode=0, stdout="abc1234\n", stderr="")
        if "status" in args:
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        return types.SimpleNamespace(returncode=-1, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _git_fake)

    registro._verificar_salud()

    assert len(mensajes) == 1, "Se debe mostrar exactamente un nuke.message"
    mensaje = mensajes[0]
    assert "Versión instalada" in mensaje
    assert "checkout git" in mensaje
    assert "abc1234" in mensaje