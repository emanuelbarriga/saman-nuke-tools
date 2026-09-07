"""
Tests del menú superior SamanTools y del buscador de Nodos (Tab).

Cubre la reestructuración aprobada: el menú superior se organiza por
categorías con "Acerca de" directo en la raíz y submenús temáticos
(Tools / Paneles / Salud). El buscador TAB solo expone "Insertar Nodo"
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

    saman = _submenu_de(menu, "SamanTools")
    assert saman is not None, "Falta el submenu 'SamanTools'"

    # Raíz: "Acerca de" y "Breakdown" como comandos directos. (Actualizar/
    # Desinstalar los agrega bootstrap/menu.py, no este módulo.)
    nombres_comandos = _nombres_comandos(saman)
    assert "Acerca de SamanTools..." in nombres_comandos
    assert "Breakdown" in nombres_comandos
    assert "Cambiar ColorSpace..." not in nombres_comandos

    # Submenús temáticos: sin "Configuración" ni estructura vieja.
    nombres_submenus = [getattr(sub, "_nombre", None) for sub in saman.items()]
    assert "Tools" in nombres_submenus
    assert "Paneles (En construcción)" in nombres_submenus
    assert "Salud" in nombres_submenus
    assert "Configuración" not in nombres_submenus
    assert "Composición" not in nombres_submenus
    assert "VFXFlow" not in nombres_submenus
    assert "Sistema / Configuración" not in nombres_submenus

    tools = _submenu_de(saman, "Tools")
    assert "Cambiar ColorSpace..." in _nombres_comandos(tools)
    assert "Breakdown" not in _nombres_comandos(tools)

    paneles = _submenu_de(saman, "Paneles (En construcción)")
    assert "Panel de Rutas" in _nombres_comandos(paneles)
    assert "Panel de Comentarios" in _nombres_comandos(paneles)
    # Atajo Ctrl+Alt+C registrado en "Panel de Comentarios".
    assert ("Panel de Comentarios", "Ctrl+Alt+C") in paneles.shortcuts

    salud = _submenu_de(saman, "Salud")
    nombres_salud = _nombres_comandos(salud)
    assert "Diagnóstico de Red" in nombres_salud
    assert "Verificar Salud del Plugin..." in nombres_salud
    assert "Escanear Scripts del Proyecto" in nombres_salud
    assert "Limpiar knobs volátiles" in nombres_salud
    assert "Limpiar knobs volátiles en carpeta..." in nombres_salud


def test_instalar_no_registra_changecolorspace_en_nodes(monkeypatch):
    menu = _instalar(monkeypatch)

    menu_saman = _submenu_de(menu, "HTLR · Saman · Samán")
    assert menu_saman is not None, "Falta el submenu 'HTLR · Saman · Samán' del buscador Tab"

    nombres_submenus = [getattr(sub, "_nombre", None) for sub in menu_saman.items()]
    assert "Utilidades" not in nombres_submenus

    def _comandos_recursivos(sub):
        for name, _cmd in sub.commands:
            yield name
        for hijo in sub.items():
            for name in _comandos_recursivos(hijo):
                yield name

    assert not any("ChangeColorspace" in name for name in _comandos_recursivos(menu_saman)), (
        "ChangeColorspace no debe registrarse en el buscador Tab"
    )

    insertar = _submenu_de(menu_saman, "Insertar Nodo")
    assert insertar is not None, "Falta el submenu 'Insertar Nodo' en el buscador Tab"
    nombres_cmd = _nombres_comandos(insertar)
    assert "Rutas (Rutas VFX)" in nombres_cmd
    assert "Review (Comparación)" in nombres_cmd
    assert "Breakdown (frames por tabla)" in nombres_cmd


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