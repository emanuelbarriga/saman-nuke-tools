"""
Tests de SamanTools.vfxflow_auth y SamanTools.sesion_vfxflow (login VFXFlow).

Puros, sin red real: se hace monkeypatch de `urllib.request.urlopen` con
respuestas JSON fabricadas (RespuestaFalsa / HTTPError). No se prueba el
widget PySide (regla del repo: 0% UI), solo la logica pura.
"""

import io
import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from SamanTools import sesion_vfxflow, vfxflow_auth, vfxflow_config
from SamanTools.vfxflow_auth import VfxFlowAuthError


class RespuestaFalsa:
    """Emula la respuesta de urlopen: `.status`, `.read()` y protocolo context."""

    def __init__(self, cuerpo, status=200):
        self._cuerpo = cuerpo
        self.status = status

    def read(self):
        return self._cuerpo

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


def _error_http(status, cuerpo):
    """Construye un HTTPError como el que urlopen lanza ante status != 2xx."""
    fp = io.BytesIO(json.dumps(cuerpo).encode("utf-8"))
    return urllib.error.HTTPError(
        "https://vfxflow.invalido", status, "Error", {}, fp
    )


def _urlopen_responde(monkeypatch, cuerpo, status=200):
    def _fake(req, *args, **kwargs):
        return RespuestaFalsa(json.dumps(cuerpo).encode("utf-8"), status=status)

    monkeypatch.setattr(urllib.request, "urlopen", _fake)


def _urlopen_lanza(monkeypatch, excepcion):
    def _fake(req, *args, **kwargs):
        raise excepcion

    monkeypatch.setattr(urllib.request, "urlopen", _fake)


# --------------------------------------------------------------------------
# loguear
# --------------------------------------------------------------------------


def test_loguear_exitoso(monkeypatch):
    _urlopen_responde(
        monkeypatch,
        {
            "idToken": "idtoken1",
            "refreshToken": "refreshtoken1",
            "expiresIn": "3600",
            "localId": "usuario123",
            "email": "artista@samanestudio.com",
        },
    )
    res = vfxflow_auth.loguear("artista@samanestudio.com", "secreto")
    assert res == {
        "id_token": "idtoken1",
        "refresh_token": "refreshtoken1",
        "expires_in": "3600",
        "local_id": "usuario123",
        "email": "artista@samanestudio.com",
    }


def test_loguear_credenciales_invalidas(monkeypatch):
    _urlopen_lanza(
        monkeypatch,
        _error_http(400, {"error": {"message": "INVALID_LOGIN_CREDENTIALS"}}),
    )
    with pytest.raises(VfxFlowAuthError) as exc:
        vfxflow_auth.loguear("artista@samanestudio.com", "secreto")
    assert exc.value.codigo == "credenciales"
    assert "secreto" not in str(exc.value)  # nunca leakear la password


@pytest.mark.parametrize(
    "excepcion",
    [socket.timeout("timed out"), urllib.error.URLError("sin red")],
)
def test_loguear_error_de_red(monkeypatch, excepcion):
    _urlopen_lanza(monkeypatch, excepcion)
    with pytest.raises(VfxFlowAuthError) as exc:
        vfxflow_auth.loguear("artista@samanestudio.com", "secreto")
    assert exc.value.codigo == "red"


# --------------------------------------------------------------------------
# refrescar_id_token
# --------------------------------------------------------------------------


def test_refrescar_id_token_exitoso(monkeypatch):
    _urlopen_responde(
        monkeypatch,
        {
            "access_token": "idtoken_nuevo",
            "refresh_token": "refreshtoken_nuevo",
            "expires_in": "3600",
            "user_id": "usuario123",
        },
    )
    res = vfxflow_auth.refrescar_id_token("refreshtoken1")
    assert res["id_token"] == "idtoken_nuevo"
    assert res["refresh_token"] == "refreshtoken_nuevo"
    assert res["expires_in"] == "3600"
    assert res["user_id"] == "usuario123"


# --------------------------------------------------------------------------
# obtener_usuario
# --------------------------------------------------------------------------


def test_obtener_usuario_con_role(monkeypatch):
    _urlopen_responde(
        monkeypatch,
        {
            "fields": {
                "role": {"stringValue": "artist"},
                "name": {"stringValue": "Ana Artista"},
                "activo": {"booleanValue": True},
                "legajo": {"integerValue": "7"},
            }
        },
    )
    res = vfxflow_auth.obtener_usuario("usuario123", "idtoken1")
    assert res["role"] == "artist"
    assert res["name"] == "Ana Artista"
    assert res["activo"] is True
    assert res["legajo"] == 7


def test_obtener_usuario_sin_documento_devuelve_rol_por_defecto(monkeypatch):
    _urlopen_lanza(monkeypatch, _error_http(404, {}))
    res = vfxflow_auth.obtener_usuario("usuario123", "idtoken1")
    assert res == {"role": "artist"}


def test_obtener_usuario_token_vencido(monkeypatch):
    _urlopen_lanza(
        monkeypatch, _error_http(401, {"error": {"message": "UNAUTHENTICATED"}})
    )
    with pytest.raises(VfxFlowAuthError) as exc:
        vfxflow_auth.obtener_usuario("usuario123", "idtoken_vencido")
    assert exc.value.codigo == "token"


# --------------------------------------------------------------------------
# sesion_vfxflow
# --------------------------------------------------------------------------


def test_guardar_y_cargar_sesion_redondea(tmp_path, monkeypatch):
    ruta = tmp_path / "sesion.json"
    monkeypatch.setattr(sesion_vfxflow, "_RUTA", str(ruta))

    ok = sesion_vfxflow.guardar_sesion(
        {
            "refresh_token": "RT_1",
            "local_id": "u1",
            "email": "a@b.co",
            "id_token": "no_persistir",
        }
    )
    assert ok is True
    assert ruta.exists()
    # Solo se persisten refresh_token/local_id/email (sin id_token).
    cargada = sesion_vfxflow.cargar_sesion()
    assert cargada == {"refresh_token": "RT_1", "local_id": "u1", "email": "a@b.co"}

    if os.name == "posix":
        assert (ruta.stat().st_mode & 0o777) == 0o600


def test_borrar_sesion(tmp_path, monkeypatch):
    ruta = tmp_path / "sesion.json"
    monkeypatch.setattr(sesion_vfxflow, "_RUTA", str(ruta))

    assert sesion_vfxflow.borrar_sesion() is False  # no existia
    sesion_vfxflow.guardar_sesion({"refresh_token": "RT_1"})
    assert sesion_vfxflow.borrar_sesion() is True
    assert not ruta.exists()


# --------------------------------------------------------------------------
# pureza (sin `import nuke`)
# --------------------------------------------------------------------------


def test_modulos_importan_sin_nuke():
    # Subproceso con `nuke` bloqueado en sys.meta_path: si un módulo de
    # SamanTools hiciera `import nuke`, el import fallaria.
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    codigo = (
        "import sys, types\n"
        "class Bloqueo:\n"
        "    def find_module(self, nombre, camino=None):\n"
        "        if nombre == 'nuke':\n"
        "            raise ImportError('nuke bloqueado')\n"
        "        return None\n"
        "    def find_spec(self, nombre, camino=None, target=None):\n"
        "        if nombre == 'nuke':\n"
        "            raise ImportError('nuke bloqueado')\n"
        "        return None\n"
        "sys.meta_path.insert(0, Bloqueo())\n"
        "sys.path.insert(0, {raiz!r})\n"
        "from SamanTools import vfxflow_auth, vfxflow_config\n"
        "print('OK')\n"
    ).format(raiz=raiz)
    res = subprocess.run(
        [sys.executable, "-c", codigo], capture_output=True, text=True
    )
    assert res.returncode == 0, res.stderr
    assert "OK" in res.stdout