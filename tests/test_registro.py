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
import subprocess
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
    monkeypatch.setattr(registro.proyecto_tools, "cargar_scripts_proyecto", lambda: False)
    monkeypatch.setattr(registro, "_inyectar_frame_manager", lambda: None)
    menu = nuke.menu("Nodes")
    menu._items[:] = []
    menu.commands[:] = []
    registro.instalar()
    return menu


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
    menu._items[:] = []
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
        (sub for sub in menu._items if getattr(sub, "_nombre", None) == "HTLR · Saman · Samán"),
        None,
    )
    assert menu_saman is not None, "Falta el submenu 'HTLR · Saman · Samán' del buscador Tab"

    insertar = next(
        (sub for sub in menu_saman.items() if getattr(sub, "_nombre", None) == "Insertar Nodo"),
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


# ---------------------------------------------------------------------------
# Funciones privadas de registro (cobertura adicional)
# ---------------------------------------------------------------------------


def test_ruta_icono_absoluta():
    ruta = registro._ruta_icono("MiIcono.svg")
    assert os.path.isabs(ruta)
    assert ruta.endswith("MiIcono.svg")


def test_escanear_scripts_ok(monkeypatch):
    monkeypatch.setattr(
        registro.proyecto_tools, "cargar_scripts_proyecto", lambda: True
    )
    registro._escanear_scripts_proyecto()
    mensaje = nuke._estado["mensajes"][-1]
    assert "Scripts del proyecto cargados" in mensaje


def test_escanear_scripts_vacio(monkeypatch):
    monkeypatch.setattr(
        registro.proyecto_tools, "cargar_scripts_proyecto", lambda: False
    )
    registro._escanear_scripts_proyecto()
    mensaje = nuke._estado["mensajes"][-1]
    assert "No se encontraron scripts" in mensaje


def test_insertar_rutas_llama_crear_o_reutilizar(monkeypatch):
    from SamanTools import rutas

    llamadas = []

    def _espia():
        llamadas.append(True)

    monkeypatch.setattr(rutas, "crear_o_reutilizar", _espia)
    registro._insertar_rutas()
    assert llamadas == [True]


def test_insertar_review_no_lanza(monkeypatch):
    from SamanTools import limpiar

    monkeypatch.setattr(limpiar, "sanitizar_archivo", lambda ruta: 0)
    # nodePaste del stub devuelve NodoFake; no debe lanzar.
    registro._insertar_review()
    assert True


def test_insertar_breakdown_no_lanza():
    registro._insertar_breakdown()
    assert True


def test_acerca_de_contiene_version(monkeypatch):
    mensajes = []
    monkeypatch.setattr(nuke, "message", mensajes.append)
    from SamanTools import __version__
    registro._acerca_de()
    assert len(mensajes) == 1
    assert "SamanTools" in mensajes[0]
    assert __version__ in mensajes[0]


def test_inyectar_frame_manager_no_lanza(monkeypatch):
    # frame_manager puede importarse o fallar con ImportError fuera de Nuke;
    # el handler lo atrapa. Solo aseguramos que no lanza.
    registro._inyectar_frame_manager()
    assert True


def test_verificar_salud_copia_sin_git(monkeypatch):
    mensajes = []
    monkeypatch.setattr(nuke, "message", mensajes.append)

    original_isdir = os.path.isdir

    def _isdir_sin_git(p):
        if p.endswith(".git"):
            return False
        return original_isdir(p)

    monkeypatch.setattr(os.path, "isdir", _isdir_sin_git)

    registro._verificar_salud()
    assert len(mensajes) == 1
    mensaje = mensajes[0]
    assert "instalación por copia" in mensaje
    assert "no aplica" in mensaje


def test_verificar_salud_git_arbol_sucio(monkeypatch):
    mensajes = []
    monkeypatch.setattr(nuke, "message", mensajes.append)

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
            return types.SimpleNamespace(returncode=0, stdout=" M archivo\n", stderr="")
        return types.SimpleNamespace(returncode=-1, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _git_fake)

    registro._verificar_salud()
    assert len(mensajes) == 1
    mensaje = mensajes[0]
    assert "checkout git" in mensaje
    assert "árbol local con cambios" in mensaje


# ---------------------------------------------------------------------------
# Botón masivo: limpiar knobs volátiles en carpeta.
# ---------------------------------------------------------------------------
# Las funciones reciben `_select_carpeta` (hook inyectable) para testear SIN
# depender de que PySide/PySide6 esté instalado en CI.


def test_limpiar_carpeta_cancela(monkeypatch):
    from SamanTools import limpiar

    llamadas = []
    monkeypatch.setattr(limpiar, "sanitizar_carpeta", lambda ruta: llamadas.append(ruta) or {})
    # Cancelar devuelve carpeta vacia -> return silencioso, no ejecuta.
    registro._limpiar_knobs_volatiles_carpeta(_select_carpeta=lambda: "")
    assert llamadas == []


def test_limpiar_carpeta_confirmado(monkeypatch, tmp_path):
    from SamanTools import limpiar

    mensajes = []
    monkeypatch.setattr(nuke, "message", mensajes.append)
    monkeypatch.setattr(limpiar, "sanitizar_carpeta", lambda ruta: {"limpiados": 2, "sin_cambios": 1, "errores": []})
    # Los 3 .nk del tmp_path activan la confirmacion (nuke.ask -> True).
    (tmp_path / "a.nk").write_text("mov64_prraw_plugin Standard\n", encoding="utf-8")
    (tmp_path / "b.nk").write_text("mov64_prraw_plugin Standard\n", encoding="utf-8")
    (tmp_path / "c.gizmo").write_text("Mov64_prraw_plugin Standard\n", encoding="utf-8")
    registro._limpiar_knobs_volatiles_carpeta(_select_carpeta=lambda: str(tmp_path))
    assert len(mensajes) == 1
    assert "Limpiados: 2" in mensajes[0]
    assert "Ya estaban limpios: 1" in mensajes[0]


def test_limpiar_carpeta_sin_archivos(monkeypatch, tmp_path):
    mensajes = []
    monkeypatch.setattr(nuke, "message", mensajes.append)
    registro._limpiar_knobs_volatiles_carpeta(_select_carpeta=lambda: str(tmp_path))
    assert len(mensajes) == 1
    assert "No se encontraron" in mensajes[0]


def test_instalar_agrega_boton_carpeta(monkeypatch):
    menu = _instalar(monkeypatch)
    saman = next(
        (sub for sub in menu._items if getattr(sub, "_nombre", None) == "SamanTools"),
        None,
    )
    assert saman is not None
    sistema = next(
        (sub for sub in saman.items() if getattr(sub, "_nombre", None) == "Configuración"),
        None,
    )
    assert sistema is not None
    nombres = [name for (name, _) in sistema.commands]
    assert "Limpiar knobs volátiles en carpeta..." in nombres
