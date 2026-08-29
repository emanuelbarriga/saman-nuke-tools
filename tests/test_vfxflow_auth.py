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


def _urlopen_responde_secuencia(monkeypatch, respuestas):
    """Devuelve cada `(cuerpo, status)` de `respuestas` en orden.

    Con la ultima entrada se queda repitiendola (util para 'sigue pendiente
    hasta que pasa algo'). status != 200 se lanza como HTTPError, igual que
    urlopen real.
    """
    pila = list(respuestas)

    def _fake(req, *args, **kwargs):
        cuerpo, status = pila[0] if len(pila) == 1 else pila.pop(0)
        if status == 200:
            return RespuestaFalsa(json.dumps(cuerpo).encode("utf-8"), status=status)
        raise _error_http(status, cuerpo)

    monkeypatch.setattr(urllib.request, "urlopen", _fake)


# Config minima con google_client_id para los tests del Device Flow
# (se pasa explicitamente a las funciones; no se muta VFXFLOW_CONFIG global).
_CONFIG_GOOGLE = {
    "api_key": "AIzaSyTEST",
    "project_id": "vfxpm-test",
    "google_client_id": "cliente-google-de-test",
}


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
# Continuar con Google (OAuth 2.0 Device Flow)
# --------------------------------------------------------------------------


def test_obtener_codigo_dispositivo_exitoso(monkeypatch):
    _urlopen_responde(
        monkeypatch,
        {
            "device_code": "dc1",
            "user_code": "ABCD-1234",
            "verification_url": "https://www.google.com/device",
            "expires_in": 1800,
            "interval": 5,
        },
    )
    res = vfxflow_auth.obtener_codigo_dispositivo(config=_CONFIG_GOOGLE)
    assert res == {
        "device_code": "dc1",
        "user_code": "ABCD-1234",
        "verification_url": "https://www.google.com/device",
        "expires_in": 1800,
        "interval": 5,
    }


def test_obtener_codigo_dispositivo_sin_google_client_id():
    with pytest.raises(VfxFlowAuthError) as exc:
        vfxflow_auth.obtener_codigo_dispositivo(
            config={"api_key": "k", "google_client_id": ""}
        )
    assert exc.value.codigo == "config"


def test_esperar_autorizacion_pending_luego_aprobada(monkeypatch):
    monkeypatch.setattr(vfxflow_auth.time, "sleep", lambda s: None)
    _urlopen_responde_secuencia(
        monkeypatch,
        [
            ({"error": "authorization_pending"}, 428),
            (
                {
                    "access_token": "at1",
                    "id_token": "idtoken_google",
                    "refresh_token": "refreshtoken_google",
                    "scope": "email profile openid",
                    "expires_in": 3600,
                },
                200,
            ),
        ],
    )
    res = vfxflow_auth.esperar_autorizacion_dispositivo(
        "dc1", intervalo=1, config=_CONFIG_GOOGLE
    )
    assert res == {
        "access_token": "at1",
        "id_token": "idtoken_google",
        "refresh_token": "refreshtoken_google",
    }


def test_esperar_autorizacion_access_denied(monkeypatch):
    monkeypatch.setattr(vfxflow_auth.time, "sleep", lambda s: None)
    _urlopen_lanza(
        monkeypatch,
        _error_http(403, {"error": "access_denied", "error_description": "no"}),
    )
    with pytest.raises(VfxFlowAuthError) as exc:
        vfxflow_auth.esperar_autorizacion_dispositivo(
            "dc1", intervalo=1, config=_CONFIG_GOOGLE
        )
    assert exc.value.codigo == "denegado"


def test_esperar_autorizacion_expirado(monkeypatch):
    reloj = {"t": 0.0}
    monkeypatch.setattr(
        vfxflow_auth.time, "sleep", lambda s: reloj.__setitem__("t", reloj["t"] + s)
    )
    monkeypatch.setattr(vfxflow_auth.time, "time", lambda: reloj["t"])
    # Respuesta unica repetida: la secuencia crea un HTTPError FRESCO en cada
    # poll (instancias compartidas se agotan tras el primer e.read()).
    _urlopen_responde_secuencia(
        monkeypatch, [({"error": "authorization_pending"}, 428)]
    )
    with pytest.raises(VfxFlowAuthError) as exc:
        vfxflow_auth.esperar_autorizacion_dispositivo(
            "dc1", intervalo=1, tiempo_maximo=300, config=_CONFIG_GOOGLE
        )
    assert exc.value.codigo == "expirado"


def test_loguear_con_google_exitoso(monkeypatch):
    _urlopen_responde(
        monkeypatch,
        {
            "idToken": "idtoken_firebase",
            "refreshToken": "refreshtoken_firebase",
            "expiresIn": "3600",
            "localId": "usuario123",
            "email": "artista@gmail.com",
        },
    )
    res = vfxflow_auth.loguear_con_google("idtoken_google", config=_CONFIG_GOOGLE)
    assert res == {
        "id_token": "idtoken_firebase",
        "refresh_token": "refreshtoken_firebase",
        "expires_in": "3600",
        "local_id": "usuario123",
        "email": "artista@gmail.com",
    }


def test_loguear_con_google_sin_token():
    with pytest.raises(VfxFlowAuthError) as exc:
        vfxflow_auth.loguear_con_google("", config=_CONFIG_GOOGLE)
    assert exc.value.codigo == "respuesta"


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