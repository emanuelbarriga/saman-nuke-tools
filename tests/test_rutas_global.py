"""
Tests de SamanTools.rutas_global: config global de rutas (panel docked).

Cubre: estructura por defecto, guardar/cargar JSON (redondeo y tolerancia a
archivo corrupto), aplicar_global (escribe PYTHON_* en __main__) y
cambiar_proyecto_global (reescritura del segmento de proyecto). Son puros
o con el stub de nuke de conftest; no requieren GUI.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import __main__
import nuke
from SamanTools import rutas
from SamanTools import rutas_global


@pytest.fixture(autouse=True)
def _escena_limpia():
    nuke._estado["nodos"] = []
    nuke._estado["mensajes"] = []
    # Aislamiento: el __main__ falso comparte estado entre tests.
    __main__.PYTHON_TO_VFX = ""
    __main__.PYTHON_COMP = ""
    __main__.PYTHON_FROM_VFX = ""
    yield
    nuke._estado["nodos"] = []
    nuke._estado["mensajes"] = []
    __main__.PYTHON_TO_VFX = ""
    __main__.PYTHON_COMP = ""
    __main__.PYTHON_FROM_VFX = ""


def _cfg_ejemplo():
    cfg = rutas_global.config_vacia()
    cfg["usuario_activo"] = "MacServer"
    cfg["proyecto"] = "HTLR"
    cfg["rutas"]["TO_VFX_SERVER_MAC"] = "/Volumes/wupm/2026/HTLR/TO_VFX"
    cfg["rutas"]["comp_SERVER_MAC"] = "/Volumes/wupm/2026/HTLR/COMP"
    cfg["rutas"]["FROM_VFX_SERVER_MAC"] = "/Volumes/wupm/2026/HTLR/FROM_VFX"
    return cfg


def test_config_vacia_tiene_las_9_rutas():
    cfg = rutas_global.config_vacia()
    assert cfg["usuario_activo"] == ""
    assert cfg["proyecto"] == ""
    assert len(cfg["rutas"]) == 9
    assert all(v == "" for v in cfg["rutas"].values())


def test_guardar_y_cargar_redondea(tmp_path):
    ruta = str(tmp_path / "rutas.json")
    cfg = _cfg_ejemplo()
    assert rutas_global.guardar_config(cfg, ruta=ruta) is True
    cargado = rutas_global.cargar_config(ruta=ruta)
    assert cargado == cfg


def test_cargar_archivo_ausente_devuelve_vacio(tmp_path):
    cfg = rutas_global.cargar_config(ruta=str(tmp_path / "no_existe.json"))
    assert cfg == rutas_global.config_vacia()


def test_cargar_archivo_corrupto_devuelve_vacio(tmp_path):
    ruta = tmp_path / "corrupto.json"
    ruta.write_text("{ esto no es json ", encoding="utf-8")
    cfg = rutas_global.cargar_config(ruta=str(ruta))
    assert cfg == rutas_global.config_vacia()


def test_guardar_es_atomico_y_crea_carpeta(tmp_path):
    ruta = str(tmp_path / "sub" / "rutas.json")
    assert rutas_global.guardar_config(_cfg_ejemplo(), ruta=ruta) is True
    assert os.path.isfile(ruta)
    assert not os.path.exists(ruta + ".tmp")


def test_aplicar_global_escribe_python_vars(monkeypatch):
    monkeypatch.setattr(rutas.proyecto, "cargar_scripts_proyecto", lambda: False)
    cfg = _cfg_ejemplo()
    ok = rutas_global.aplicar_global(cfg)
    assert ok is False  # cargar_scripts_proyecto devuelve False
    assert __main__.PYTHON_TO_VFX == "/Volumes/wupm/2026/HTLR/TO_VFX"
    assert __main__.PYTHON_COMP == "/Volumes/wupm/2026/HTLR/COMP"
    assert __main__.PYTHON_FROM_VFX == "/Volumes/wupm/2026/HTLR/FROM_VFX"


def test_aplicar_global_usuario_invalido_no_aplica(monkeypatch):
    monkeypatch.setattr(rutas.proyecto, "cargar_scripts_proyecto", lambda: False)
    cfg = _cfg_ejemplo()
    cfg["usuario_activo"] = "Invalido"
    assert rutas_global.aplicar_global(cfg) is False
    assert __main__.PYTHON_TO_VFX == ""


def test_cambiar_proyecto_global_reescribe_segmento():
    cfg = _cfg_ejemplo()
    nuevo, cambios = rutas_global.cambiar_proyecto_global(cfg, "SAMAN")
    assert cambios == 3
    assert nuevo["proyecto"] == "SAMAN"
    assert nuevo["rutas"]["TO_VFX_SERVER_MAC"] == "/Volumes/wupm/2026/SAMAN/TO_VFX"
    assert nuevo["rutas"]["comp_SERVER_MAC"] == "/Volumes/wupm/2026/SAMAN/COMP"
    assert nuevo["rutas"]["FROM_VFX_SERVER_MAC"] == "/Volumes/wupm/2026/SAMAN/FROM_VFX"
    # cfg original no se muta
    assert cfg["proyecto"] == "HTLR"


def test_cambiar_proyecto_global_sin_cambios_devuelve_misma():
    cfg = _cfg_ejemplo()
    cfg["rutas"] = {k: "" for k in rutas_global.KNOBS_CONFIG}
    nuevo, cambios = rutas_global.cambiar_proyecto_global(cfg, "SAMAN")
    assert cambios == 0
    assert nuevo is cfg  # sin cambios no se copia


def test_importar_desde_nodo_vacia_a_none():
    cfg = rutas_global.config_vacia()
    assert rutas_global.importar_desde_nodo(cfg, None) == cfg


def test_reescribir_proyecto_puro():
    rutas_dict = {
        "TO_VFX_SERVER_MAC": "/Volumes/wupm/2026/HTLR/TO_VFX",
        "comp_SERVER_MAC": "/Volumes/wupm/2026/HTLR/COMP",
        "TO_VFX_SERVER_WINDOWS": "L:/2026/HTLR/TO_VFX",
    }
    nuevo, cambios = rutas._reescribir_proyecto_en_rutas(rutas_dict, "NUEVO")
    assert cambios == 3
    assert nuevo["TO_VFX_SERVER_WINDOWS"] == "L:/2026/NUEVO/TO_VFX"