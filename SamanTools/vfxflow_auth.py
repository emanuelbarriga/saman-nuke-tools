"""
SamanTools.vfxflow_auth - Cliente REST de autenticacion contra VFXFlow.

Se conecta directo a los endpoints de Firebase Identity Platform y Cloud
Firestore via REST (sin SDK), para correr en el Python de Nuke y poder
testearse con pytest puro (sin `import nuke`).

Flujo de login:
    1. POST /v1/accounts:signInWithPassword  -> id_token + refresh_token.
    2. GET  /v1/projects/{project}/databases/(default)/documents/users/{uid}
       con `Authorization: Bearer <id_token>` -> rol del usuario (doc plano).

El id_token (1 hora) se renueva con securetoken (REST). Las llamadas HTTP
usan `urllib.request` (stdlib, sin dependencias) con timeout de 10 s y
NUNCA incluyen credenciales (password / tokens) en los mensajes de error.
"""

import json
import socket
import urllib.error
import urllib.request

from .vfxflow_config import VFXFLOW_CONFIG

# Timeout de red para todas las llamadas (segundos).
TIMEOUT_SEGUNDOS = 10

URL_SIGN_IN = (
    "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
    "?key={api_key}"
)
URL_REFRESH_TOKEN = "https://securetoken.googleapis.com/v1/token?key={api_key}"
URL_DOCUMENTO_USUARIO = (
    "https://firestore.googleapis.com/v1/projects/{project_id}"
    "/databases/(default)/documents/users/{local_id}"
)


class VfxFlowAuthError(Exception):
    """Error controlado de la autenticacion contra VFXFlow.

    `codigo` distingue la naturaleza del fallo:
        "credenciales" -> email/password invalidos
        "red"          -> timeout / sin conexion
        "http"         -> la API respondio con un status HTTP inesperado
        "token"        -> el id_token expiro (401 en Firestore)
        "respuesta"    -> la API devolvio algo inesperado
    """

    def __init__(self, mensaje, codigo="respuesta"):
        super().__init__(mensaje)
        self.codigo = codigo


# --------------------------------------------------------------------------
# Transporte HTTP (no exponer en la API publica del modulo)
# --------------------------------------------------------------------------


def _post_json(url, payload, api_key):
    """POST JSON y devuelve el objeto parseado.

    `api_key` viaja en la URL (modelo REST de Firebase); el parametro se
    conserva por contrato de firma y para auditoria de la llamada.
    Levanta `VfxFlowAuthError` con codigo credenciales/red/http/respuesta.
    """
    cuerpo = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=cuerpo, method="POST")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as respuesta:
            texto = respuesta.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        _levantar_error_http(e, es_firestore=False)
    except (urllib.error.URLError, socket.timeout):
        raise VfxFlowAuthError(
            "No se pudo contactar VFXFlow (revisá tu conexión a internet).",
            codigo="red",
        )

    try:
        return json.loads(texto)
    except (ValueError, TypeError):
        raise VfxFlowAuthError(
            "VFXFlow respondió con un JSON inválido.", codigo="respuesta"
        )


def _get_con_bearer(url, id_token):
    """GET con `Authorization: Bearer <id_token>` y devuelve el objeto parsed.

    HTTP 401 -> codigo "token" (id_token vencido). HTTP 404 -> None (el doc
    de Firestore aun no existe). Los demas errores -> codigo "http"/"red".
    """
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", "Bearer {0}".format(id_token))

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as respuesta:
            texto = respuesta.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        # _levantar_error_http lanza (401/http) o devuelve None (404).
        return _levantar_error_http(e, es_firestore=True)
    except (urllib.error.URLError, socket.timeout):
        raise VfxFlowAuthError(
            "No se pudo contactar VFXFlow (revisá tu conexión a internet).",
            codigo="red",
        )

    try:
        return json.loads(texto)
    except (ValueError, TypeError):
        raise VfxFlowAuthError(
            "VFXFlow respondió con un JSON inválido.", codigo="respuesta"
        )


def _levantar_error_http(e, es_firestore=False):
    """Convierte un HTTPError de urllib en un VfxFlowAuthError con codigo."""
    mensaje_servidor = ""
    try:
        cuerpo_error = json.loads(e.read().decode("utf-8"))
        mensaje_servidor = (cuerpo_error.get("error") or {}).get("message", "") or ""
    except Exception:
        mensaje_servidor = ""

    if e.code == 401:
        raise VfxFlowAuthError(
            "La sesión de VFXFlow expiró; volvé a iniciar sesión.",
            codigo="token",
        )
    if not es_firestore and e.code == 400 and "INVALID_LOGIN_CREDENTIALS" in mensaje_servidor:
        raise VfxFlowAuthError(
            "Email o contraseña incorrectos (credenciales inválidas).",
            codigo="credenciales",
        )
    if es_firestore and e.code == 404:
        # Documento inexistente en users/{uid}: se trata como rol por defecto.
        return None
    raise VfxFlowAuthError(
        "La API de VFXFlow respondió con un error HTTP ({0}).".format(e.code),
        codigo="http",
    )


# --------------------------------------------------------------------------
# Respuestas de Firestore
# --------------------------------------------------------------------------


def _aplanar_firestore_fields(fields):
    """Convierte `fields` de Firestore (REST) en un dict plano de Python.

    Ejemplo:
        {"role": {"stringValue": "artist"}}  ->  {"role": "artist"}

    Soportados: stringValue, booleanValue, integerValue, doubleValue,
    timestampValue y nullValue. Los valores desconocidos se omiten.
    """
    planos = {}
    if not isinstance(fields, dict):
        return planos
    for clave, valor in fields.items():
        if not isinstance(valor, dict):
            planos[clave] = valor
            continue
        if "stringValue" in valor:
            planos[clave] = valor["stringValue"]
        elif "booleanValue" in valor:
            planos[clave] = valor["booleanValue"] in (True, "true", "TRUE")
        elif "integerValue" in valor:
            try:
                planos[clave] = int(valor["integerValue"])
            except (TypeError, ValueError):
                planos[clave] = valor["integerValue"]
        elif "doubleValue" in valor:
            planos[clave] = valor["doubleValue"]
        elif "timestampValue" in valor:
            planos[clave] = valor["timestampValue"]
        elif "nullValue" in valor:
            planos[clave] = None
    return planos


# --------------------------------------------------------------------------
# API publica
# --------------------------------------------------------------------------

_API_KEY_CAMPO = "api_key"
_PROJECT_ID_CAMPO = "project_id"


def loguear(email, password, config=None):
    """Inicia sesion con email/password contra VFXFlow.

    Devuelve: {"id_token", "refresh_token", "expires_in", "local_id", "email"}.
    Levanta `VfxFlowAuthError`: codigo "credenciales" (bad credentials),
    "red", "http" o "respuesta". NUNCA incluye la password en excepciones.
    """
    cfg = config or VFXFLOW_CONFIG
    if not email or not password:
        raise VfxFlowAuthError(
            "Ingresá email y contraseña.", codigo="credenciales"
        )

    url = URL_SIGN_IN.format(api_key=cfg[_API_KEY_CAMPO])
    payload = {"email": email, "password": password, "returnSecureToken": True}
    respuesta = _post_json(url, payload, cfg[_API_KEY_CAMPO])

    try:
        return {
            "id_token": respuesta["idToken"],
            "refresh_token": respuesta["refreshToken"],
            "expires_in": str(respuesta["expiresIn"]),
            "local_id": respuesta["localId"],
            "email": respuesta["email"],
        }
    except (KeyError, TypeError):
        raise VfxFlowAuthError(
            "VFXFlow respondió sin los campos esperados.", codigo="respuesta"
        )


def refrescar_id_token(refresh_token, config=None):
    """Renueva el id_token con el refresh_token (securetoken REST).

    Devuelve: {"id_token", "refresh_token", "expires_in", "user_id"}.
    El id_token renovado viaja como `access_token` en la respuesta de
    securetoken y se renombra a `id_token`.
    """
    cfg = config or VFXFLOW_CONFIG
    if not refresh_token:
        raise VfxFlowAuthError(
            "No hay sesión guardada para refrescar.", codigo="respuesta"
        )

    url = URL_REFRESH_TOKEN.format(api_key=cfg[_API_KEY_CAMPO])
    payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    respuesta = _post_json(url, payload, cfg[_API_KEY_CAMPO])

    try:
        return {
            "id_token": respuesta["access_token"],
            "refresh_token": respuesta.get("refresh_token") or refresh_token,
            "expires_in": str(respuesta["expires_in"]),
            "user_id": respuesta["user_id"],
        }
    except (KeyError, TypeError):
        raise VfxFlowAuthError(
            "VFXFlow respondió sin los campos esperados.", codigo="respuesta"
        )


def obtener_usuario(local_id, id_token, config=None):
    """Lee el doc `users/{local_id}` en Firestore y lo devuelve aplanado.

    Devuelve {"role": "artist", ...resto} o {"role": "artist"} si el doc no
    existe o no tiene rol (404 / sin campo role / doc sin estructura).
    Levanta `VfxFlowAuthError` codigo "token" si el id_token vence (401).
    """
    cfg = config or VFXFLOW_CONFIG
    url = URL_DOCUMENTO_USUARIO.format(
        project_id=cfg[_PROJECT_ID_CAMPO], local_id=local_id
    )
    doc = _get_con_bearer(url, id_token)
    if not isinstance(doc, dict) or "fields" not in doc:
        return {"role": "artist"}

    usuario = _aplanar_firestore_fields(doc["fields"])
    rol = usuario.get("role")
    if not rol:
        usuario["role"] = "artist"
    return usuario