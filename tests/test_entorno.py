"""
Tests de SamanTools.entorno y de la integracion entorno <-> rutas.

entorno es puro (sin nuke) y testeable con pytest. Los tests de integracion
usan el stub de nuke del conftest (NodoFake/KnobFake).

No se cubre el timeout REAL (lento/flaky): se mockea subprocess.run.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import nuke
from SamanTools import entorno
from SamanTools import rutas


@pytest.fixture(autouse=True)
def _cache_estado_limpio():
    """Cache a nivel de modulo: purga antes y despues de cada test."""
    entorno._cache.clear()
    yield
    entorno._cache.clear()
    rutas._refrescando = False


# --------------------------------------------------------------------------
# detectar_so / sufijo_so / usuario_activo
# --------------------------------------------------------------------------


def test_detectar_so_devuelve_so_valido():
    assert entorno.detectar_so() in ("macOS", "Windows", "Linux")


@pytest.mark.parametrize(
    "so,sufijo,usuario",
    [
        ("macOS", "MAC", "MacServer"),
        ("Windows", "WINDOWS", "Windows"),
        ("Linux", "ARTIST", "Artist"),
    ],
)
def test_tabla_so_sufijo_usuario(so, sufijo, usuario):
    assert entorno.sufijo_so(so) == sufijo
    assert entorno.usuario_activo(so) == usuario


# --------------------------------------------------------------------------
# rutas_base
# --------------------------------------------------------------------------


def test_rutas_base_macos():
    r = entorno.rutas_base("macOS")
    assert r[0] == "/Volumes/wupm/2026"
    assert "/Volumes/wupmCloud/2026" in r


def test_rutas_base_linux():
    r = entorno.rutas_base("Linux")
    assert r[0] == "/mnt/wupm/2026"


def test_rutas_base_extra_va_primera():
    r = entorno.rutas_base("macOS", extra="/miespacio/prueba")
    assert r[0] == "/miespacio/prueba"
    assert "/Volumes/wupm/2026" in r


def test_rutas_base_windows_escanea_letras(monkeypatch):
    reales = {"L:/2026", "Z:/2026", "T:/2026"}

    def falso_isdir(p):
        return p in reales

    monkeypatch.setattr(entorno.os.path, "isdir", falso_isdir)
    r = entorno.rutas_base("Windows")
    assert r[0] == "L:/2026"
    assert r.count("L:/2026") == 1  # la L no se duplica
    assert "Z:/2026" in r
    assert "T:/2026" in r


# --------------------------------------------------------------------------
# estado_unidad
# --------------------------------------------------------------------------


def test_estado_unidad_conectado(tmp_path):
    ruta = str(tmp_path)
    res = entorno.estado_unidad(ruta)
    assert res["conectado"] is True
    assert res["ruta"] == ruta
    assert res["detalle"]


def test_estado_unidad_ruta_inexistente():
    res = entorno.estado_unidad("/ruta/que/no/existe/SamanToolsXYZ987")
    assert res["conectado"] is False
    assert res["ruta"] is None
    assert res["detalle"]


def test_estado_unidad_vacia():
    res = entorno.estado_unidad("")
    assert res["conectado"] is False
    assert res["ruta"] is None


def test_estado_unidad_none():
    assert entorno.estado_unidad(None)["conectado"] is False


def test_estado_unidad_timeout_se_considera_desconectado(monkeypatch):
    def _colgar(*a, **k):
        raise subprocess.TimeoutExpired(["ls", "-d", "/ruta/colgada"], 3)

    monkeypatch.setattr(entorno.subprocess, "run", _colgar)
    res = entorno.estado_unidad("/Volumes/wupm/2026")
    assert res["conectado"] is False
    assert res["ruta"] is None
    assert "timeout" in res["detalle"].lower()


def test_estado_unidad_usa_cache(monkeypatch, tmp_path):
    ruta = str(tmp_path)
    llamadas = []
    real = entorno._verificar_ruta

    def contar(p):
        llamadas.append(p)
        return real(p)

    monkeypatch.setattr(entorno, "_verificar_ruta", contar)
    entorno.estado_unidad(ruta)
    entorno.estado_unidad(ruta)
    assert len(llamadas) == 1  # la segunda consulta sale de cache


# --------------------------------------------------------------------------
# primera_ruta_disponible
# --------------------------------------------------------------------------


def test_primera_ruta_disponible_extra(tmp_path):
    ruta = str(tmp_path)
    assert entorno.primera_ruta_disponible("macOS", extra=ruta) == ruta


def test_primera_ruta_disponible_ninguna(monkeypatch):
    monkeypatch.setattr(
        entorno, "rutas_base", lambda so, extra=None: ["/no/existe/SamanTools/nope"]
    )
    assert entorno.primera_ruta_disponible("macOS") is None


# --------------------------------------------------------------------------
# reconstruir_rutas
# --------------------------------------------------------------------------


def test_reconstruir_rutas_genera_9_claves(tmp_path):
    r = entorno.reconstruir_rutas("/Volumes/wupm/2026", "HTLR")
    assert len(r) == 9
    assert r["TO_VFX_SERVER_MAC"] == "/Volumes/wupm/2026/HTLR/TO_VFX/"
    assert r["comp_SERVER_MAC"] == "/Volumes/wupm/2026/HTLR/COMP/"
    assert r["FROM_VFX_SERVER_MAC"] == "/Volumes/wupm/2026/HTLR/FROM_VFX/"
    assert r["TO_VFX_SERVER_WINDOWS"] == "/Volumes/wupm/2026/HTLR/TO_VFX/"
    assert r["comp_SERVER_ARTIST"] == "/Volumes/wupm/2026/HTLR/COMP/"
    assert r["FROM_VFX_SERVER_ARTIST"] == "/Volumes/wupm/2026/HTLR/FROM_VFX/"


def test_reconstruir_rutas_windows_forward_slashes():
    r = entorno.reconstruir_rutas("L:/2026", "PCF")
    assert r["TO_VFX_SERVER_WINDOWS"] == "L:/2026/PCF/TO_VFX/"
    assert "\\" not in r["TO_VFX_SERVER_WINDOWS"]


def test_reconstruir_rutas_limpia_slashes_y_espacios():
    r = entorno.reconstruir_rutas("/Volumes/wupm/2026/", " HTLR ")
    assert r["TO_VFX_SERVER_MAC"] == "/Volumes/wupm/2026/HTLR/TO_VFX/"


def test_reconstruir_rutas_claves_exactas_de_los_knobs():
    r = entorno.reconstruir_rutas("L:/2026", "HTLR")
    esperadas = {
        "TO_VFX_SERVER_MAC",
        "comp_SERVER_MAC",
        "FROM_VFX_SERVER_MAC",
        "TO_VFX_SERVER_WINDOWS",
        "comp_SERVER_WINDOWS",
        "FROM_VFX_SERVER_WINDOWS",
        "TO_VFX_SERVER_ARTIST",
        "comp_SERVER_ARTIST",
        "FROM_VFX_SERVER_ARTIST",
    }
    assert set(r.keys()) == esperadas


# --------------------------------------------------------------------------
# Integracion entorno <-> rutas (nodo con knobs de entorno)
# --------------------------------------------------------------------------


def _nodo_rutas_env(usuario="MacServer", ruta_base=""):
    n = nuke.NodoFake(cls="NoOp", nombre="Rutas1")
    n.knobs_d["UsuarioActivo"] = nuke.KnobFake(usuario)
    n.knobs_d["TO_VFX_SERVER_MAC"] = nuke.KnobFake("/vol/TO_VFX")
    n.knobs_d["comp_SERVER_MAC"] = nuke.KnobFake("/vol/COMP")
    n.knobs_d["FROM_VFX_SERVER_MAC"] = nuke.KnobFake("/vol/FROM_VFX")
    n.knobs_d["RutaActual"] = nuke.KnobFake("")
    n.knobs_d["SO_Detectado"] = nuke.KnobFake("")
    n.knobs_d["RutaBase"] = nuke.KnobFake(ruta_base)
    n.knobs_d["EstadoUnidad"] = nuke.KnobFake("")
    n.knobs_d["tile_color"] = nuke.KnobFake(0)
    return n


def _escenario(n):
    nuke._estado["nodos"] = [n]
    nuke._estado["nodo_actual"] = n
    nuke._estado["mensajes"] = []


def test_actualizar_sincroniza_knobs_entorno(tmp_path):
    ruta = str(tmp_path)
    n = _nodo_rutas_env(ruta_base=ruta)
    _escenario(n)
    assert rutas.actualizar(n) is not None
    assert n["SO_Detectado"].value() in ("macOS", "Windows", "Linux")
    assert n["RutaBase"].value() == ruta
    assert "Conectado" in n["EstadoUnidad"].value()


def test_actualizar_rellena_rutabase_vacia(monkeypatch, tmp_path):
    ruta = str(tmp_path)
    n = _nodo_rutas_env(ruta_base="")
    monkeypatch.setattr(
        entorno, "primera_ruta_disponible", lambda so, extra=None: ruta or None
    )
    _escenario(n)
    assert rutas.actualizar(n) is not None
    assert n["RutaBase"].value() == ruta


def test_actualizar_nodo_sin_knobs_entorno_no_rompe():
    n = nuke.NodoFake(cls="NoOp", nombre="Rutas1")
    n.knobs_d["UsuarioActivo"] = nuke.KnobFake("MacServer")
    n.knobs_d["TO_VFX_SERVER_MAC"] = nuke.KnobFake("/vol/TO_VFX")
    n.knobs_d["comp_SERVER_MAC"] = nuke.KnobFake("/vol/COMP")
    n.knobs_d["FROM_VFX_SERVER_MAC"] = nuke.KnobFake("/vol/FROM_VFX")
    n.knobs_d["RutaActual"] = nuke.KnobFake("")
    _escenario(n)
    import __main__

    assert rutas.actualizar(n) is not None
    assert getattr(__main__, "PYTHON_TO_VFX", None) == "/vol/TO_VFX"


def test_refrescar_estado_conectado_pinta_verde(tmp_path):
    ruta = str(tmp_path)
    n = _nodo_rutas_env(ruta_base=ruta)
    assert rutas.refrescar_estado(n) is True
    assert n["SO_Detectado"].value() in ("macOS", "Windows", "Linux")
    assert n["RutaBase"].value() == ruta
    assert "Conectado" in n["EstadoUnidad"].value()
    assert n["tile_color"].value() == 0x6aff55ff


def test_refrescar_estado_desconectado_pinta_rojo():
    n = _nodo_rutas_env()
    n["RutaBase"].setValue("/no/existe/SamanTools/ruta/bogus")
    assert rutas.refrescar_estado(n) is True
    assert n["tile_color"].value() == 0xff3b30ff
    assert "Desconectado" in n["EstadoUnidad"].value()


def test_refrescar_estado_nodo_sin_knobs_no_lanza():
    n = nuke.NodoFake(cls="NoOp", nombre="Rutas1")
    n.knobs_d["file"] = nuke.KnobFake("x")
    assert rutas.refrescar_estado(n) is True


def test_refrescar_estado_sin_nodo_devuelve_false():
    nuke._estado["nodo_actual"] = None
    assert rutas.refrescar_estado(None) is False