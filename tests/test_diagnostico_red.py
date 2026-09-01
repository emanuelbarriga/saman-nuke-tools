"""
Tests de SamanTools.diagnostico_red: diagnosticador de conectividad para el
login VFXFlow. No se hace red real: se monkeypatcha urllib.request.urlopen y
las dependencias de proxy.
"""

import os
import sys
import types
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from SamanTools import diagnostico_red


class _RespuestaFake:
    """Context manager que imita la respuesta de urllib.request.urlopen."""

    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_probar_url_http_ok(monkeypatch):
    def _fake_urlopen(url, timeout):
        return _RespuestaFake(status=200)

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    ok, detalle = diagnostico_red._probar_url("https://ejemplo.test/")
    assert ok is True
    assert detalle == "HTTP 200"


def test_probar_url_http_error(monkeypatch):
    def _fake_urlopen(url, timeout):
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    ok, detalle = diagnostico_red._probar_url("https://ejemplo.test/404")
    assert ok is True
    assert detalle == "HTTPError 404"


def test_probar_url_url_error(monkeypatch):
    def _fake_urlopen(url, timeout):
        raise urllib.error.URLError(ValueError("sin DNS"))

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    ok, detalle = diagnostico_red._probar_url("https://ejemplo.test/")
    assert ok is False
    assert "URLError:" in detalle


def test_probar_url_excepcion_generica(monkeypatch):
    def _fake_urlopen(url, timeout):
        raise RuntimeError("boom generico")

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    ok, detalle = diagnostico_red._probar_url("https://ejemplo.test/")
    assert ok is False
    assert detalle.startswith("RuntimeError:")


def _instalar_vfxflow_auth_falso(monkeypatch, comportamiento):
    """Reemplaza `SamanTools.vfxflow_auth` por un modulo falso.

    Parcha TANTO sys.modules como el atributo del paquete SamanTools: en la
    suite completa otro test importa el modulo real y lo cachea como atributo
    del paquete, de modo que `from SamanTools import vfxflow_auth` ignoraria
    un fake solo en sys.modules. `comportamiento` es el callable que hace de
    `_proxy_configurado`.
    """
    import SamanTools

    modulo_falso = types.ModuleType("SamanTools.vfxflow_auth")
    modulo_falso._proxy_configurado = comportamiento
    monkeypatch.setitem(sys.modules, "SamanTools.vfxflow_auth", modulo_falso)
    monkeypatch.setattr(SamanTools, "vfxflow_auth", modulo_falso, raising=False)


def test_proxy_detectado_dato(monkeypatch):
    _instalar_vfxflow_auth_falso(monkeypatch, lambda: "http://proxy:8080")
    assert diagnostico_red._proxy_detectado() == "http://proxy:8080"


def test_proxy_detectado_error(monkeypatch):
    # _proxy_configurado lanza ImportError (simula el modulo ausente/roto).
    def _boom():
        raise ImportError("simulado: modulo ausente")

    _instalar_vfxflow_auth_falso(monkeypatch, _boom)

    res = diagnostico_red._proxy_detectado()
    assert res.startswith("ERROR al detectar proxy")


def test_ejecutar_muestra_diagnostico(monkeypatch, capsys):
    monkeypatch.setattr(
        diagnostico_red, "_proxy_detectado", lambda: "http://proxy:8080"
    )

    contador = {"i": 0}

    def _fake_probar(url):
        # Alterna OK/FAIL con ciclos para cubrir los 5 dominios.
        if contador["i"] % 2 == 0:
            resultado = (True, "HTTP 200")
        else:
            resultado = (False, "URLError: sin DNS")
        contador["i"] += 1
        return resultado

    monkeypatch.setattr(diagnostico_red, "_probar_url", _fake_probar)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy:8080")

    diagnostico_red.ejecutar()

    out = capsys.readouterr().out
    assert "Diagnostico de red VFXFlow" in out
    assert "Proxy env" in out
    assert "Proxy detectado por el panel" in out
    assert "OK " in out
    assert "FAIL" in out
    # Debe marcar los 5 dominios.
    for dominio in diagnostico_red.DOMINIOS:
        assert dominio in out
