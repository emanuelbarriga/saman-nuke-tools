"""
SamanTools.vfxflow_auth - Cliente REST de autenticacion contra VFXFlow.

Se conecta directo a los endpoints de Firebase Identity Platform y Cloud
Firestore via REST (sin SDK), para correr en el Python de Nuke y poder
testearse con pytest puro (sin `import nuke`).

Flujo de login:
    1. POST /v1/accounts:signInWithPassword  -> id_token + refresh_token.
    2. GET  /v1/projects/{project}/databases/(default)/documents/users/{uid}
       con `Authorization: Bearer <id_token>` -> rol del usuario (doc plano).

Flujo "Continuar con Google" (Device Flow, OAuth 2.0 de Google):
    1. POST oauth2.googleapis.com/device/code -> device_code + user_code.
    2. Polling oauth2.googleapis.com/token      -> id_token de GOOGLE (los
       estados intermedios son authorization_pending / slow_down /
       access_denied).
    3. POST /v1/accounts:signInWithIdp con ese id_token de Google -> la MISMA
       sesion que el login email/password. El refresh_token persistido es el
       de Firebase; el refresh_token de GOOGLE se usa una sola vez dentro del
       flujo y NUNCA se guarda.

Flujo "Continuar con Google" (escritorio, OAuth 2.0 loopback + PKCE):
    1. GET accounts.google.com/o/oauth2/v2/auth con code_challenge (S256) y
       redirect_uri `http://127.0.0.1:<puerto>` (un mini server HTTP local
       captura el code del callback).
    2. POST oauth2.googleapis.com/token (grant_type=authorization_code) con
       el code y el code_verifier -> id_token de GOOGLE.
    3. Ese id_token se canjea en Firebase con signInWithIdp (la MISMA sesion
       que email/password y que el Device Flow). El refresh_token de GOOGLE
       se usa una sola vez dentro del flujo y NUNCA se guarda.

El id_token (1 hora) se renueva con securetoken (REST). Las llamadas HTTP
usan `urllib.request` (stdlib, sin dependencias) con timeout de 10 s y
NUNCA incluyen credenciales (password / tokens) en los mensajes de error.
"""

import base64
import hashlib
import http.server
import json
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import vfxflow_config

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
URL_DEVICE_CODE = "https://oauth2.googleapis.com/device/code"
URL_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
URL_SIGN_IN_IDP = (
    "https://identitytoolkit.googleapis.com/v1/accounts:signInWithIdp?key={api_key}"
)
URL_AUTORIZACION = "https://accounts.google.com/o/oauth2/v2/auth"


class VfxFlowAuthError(Exception):
    """Error controlado de la autenticacion contra VFXFlow.

    `codigo` distingue la naturaleza del fallo:
        "credenciales" -> email/password invalidos
        "red"          -> timeout / sin conexion
        "http"         -> la API respondio con un status HTTP inesperado
        "token"        -> el id_token expiro (401 en Firestore)
        "respuesta"    -> la API devolvio algo inesperado
        "config"       -> falta configuracion (p.ej. google_client_id vacio)
        "denegado"     -> el usuario denego el Device Flow de Google
        "expirado"     -> se agoto el tiempo para autorizar el dispositivo
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


def _leer_error_oauth(e):
    """Extrae (codigo, mensaje) del body JSON de un HTTPError de OAuth.

    El cuerpo de un error de OAuth es {"error": "<codigo>",
    "error_description": "<mensaje>"}. Si el body no es parseable, devuelve
    ("http", "") para no inventar un codigo de OAuth.
    """
    try:
        cuerpo_error = json.loads(e.read().decode("utf-8"))
        codigo = cuerpo_error.get("error") or "http"
        mensaje = cuerpo_error.get("error_description") or ""
    except Exception:
        codigo, mensaje = "http", ""
    return codigo, mensaje


def _post_form(url, datos):
    """POST form-urlencoded y devuelve un dict con `estado`.

    Eleccion de diseno: a diferencia de `_post_json`, los HTTPError de OAuth
    NO lanzan excepcion (salvo red/JSON invalido). Devuelve:
        {"estado": "ok", "datos": {parsed JSON}}                  si 2xx
        {"estado": "error", "codigo": "<oauth error>",
         "mensaje": "<descripcion>"}                              si HTTPError
    Asi el polling del Device Flow distingue authorization_pending (428),
    access_denied (403) y slow_down (403) sin romper el bucle. Solo
    URLError/timeout (codigo "red") y JSON invalido ("respuesta") lanzan
    VfxFlowAuthError, porque son fallos que el polling no puede "esperar".
    """
    cuerpo = urllib.parse.urlencode(datos).encode("utf-8")
    req = urllib.request.Request(url, data=cuerpo, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as respuesta:
            texto = respuesta.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        codigo, mensaje = _leer_error_oauth(e)
        return {"estado": "error", "codigo": codigo, "mensaje": mensaje}
    except (urllib.error.URLError, socket.timeout):
        raise VfxFlowAuthError(
            "No se pudo contactar Google (revisá tu conexión a internet).",
            codigo="red",
        )

    try:
        return {"estado": "ok", "datos": json.loads(texto)}
    except (ValueError, TypeError):
        raise VfxFlowAuthError(
            "Google respondió con un JSON inválido.", codigo="respuesta"
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
    cfg = config or vfxflow_config.obtener_config_efectiva()
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


# --------------------------------------------------------------------------
# Continuar con Google (OAuth 2.0 Device Flow)
# --------------------------------------------------------------------------


def _validar_google_client_id(cfg):
    """Valida que `google_client_id` este configurado; lanza si falta."""
    google_client_id = (cfg or {}).get("google_client_id", "")
    if not google_client_id:
        raise VfxFlowAuthError(
            "Falta google_client_id. Creá el archivo .saman/vfxflow_config.json "
            "en la raíz de la unidad (ej. /Volumes/wupm/2026) con "
            '{"google_client_id": "..."}, o ponelo en config_local.py '
            "(VFXFLOW_LOCAL_CONFIG).",
            codigo="config",
        )
    return google_client_id


def obtener_codigo_dispositivo(config=None):
    """Inicia el Device Flow de Google y devuelve lo que ve el usuario.

    Devuelve: {"device_code", "user_code", "verification_url", "expires_in",
    "interval"}. Requiere `google_client_id` configurado; si falta lanza
    VfxFlowAuthError codigo "config".
    """
    cfg = config or vfxflow_config.obtener_config_efectiva()
    google_client_id = _validar_google_client_id(cfg)

    respuesta = _post_form(
        URL_DEVICE_CODE,
        {"client_id": google_client_id, "scope": "email profile openid"},
    )
    if respuesta["estado"] == "error":
        raise VfxFlowAuthError(
            "Google no pudo iniciar el flujo de dispositivo (%s)."
            % respuesta["codigo"],
            codigo="http",
        )
    datos = respuesta["datos"]
    try:
        return {
            "device_code": datos["device_code"],
            "user_code": datos["user_code"],
            "verification_url": datos["verification_url"],
            "expires_in": datos["expires_in"],
            "interval": datos["interval"],
        }
    except (KeyError, TypeError):
        raise VfxFlowAuthError(
            "Google respondió sin los campos del device flow.",
            codigo="respuesta",
        )


def consultar_estado_dispositivo(device_code, config=None):
    """Un solo tick del polling del Device Flow de Google (NO bloqueante).

    Consulta el token endpoint una vez y devuelve un dict normalizado:
        {"estado": "ok", "datos": {"access_token", "id_token",
         "refresh_token"}}                                     si aprobo
    o
        {"estado": "error", "codigo": "authorization_pending" | "slow_down" |
         "access_denied" | "http" | ..., "mensaje": "..."}

    No duerme ni reintenta: es la pieza que `esperar_autorizacion_dispositivo`
    repite en su bucle y la que la UI (QTimer del panel) llama por tick para
    no congelar Nuke. El `id_token` es el de GOOGLE (el unico que sirve para
    canjear en Firebase). El `refresh_token` de GOOGLE NUNCA se persiste.
    """
    cfg = config or vfxflow_config.obtener_config_efectiva()
    google_client_id = _validar_google_client_id(cfg)
    if not device_code:
        raise VfxFlowAuthError(
            "No hay device_code para consultar.", codigo="respuesta"
        )

    respuesta = _post_form(
        URL_GOOGLE_TOKEN,
        {
            "client_id": google_client_id,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        },
    )
    if respuesta["estado"] == "error":
        return respuesta
    datos = respuesta["datos"]
    try:
        return {
            "estado": "ok",
            "datos": {
                "access_token": datos["access_token"],
                "id_token": datos["id_token"],
                "refresh_token": datos["refresh_token"],
            },
        }
    except (KeyError, TypeError):
        raise VfxFlowAuthError(
            "Google respondió sin los tokens esperados.", codigo="respuesta"
        )


def esperar_autorizacion_dispositivo(
    device_code, intervalo, tiempo_maximo=300, config=None
):
    """Hace polling hasta que el usuario autoriza el dispositivo en Google.

    Llama `consultar_estado_dispositivo` cada `intervalo` segundos (suma 5 s
    ante slow_down) hasta `tiempo_maximo`. Al aprobar devuelve
    {"access_token", "id_token", "refresh_token"} (id_token de GOOGLE).
    Lanza VfxFlowAuthError: "denegado" si el usuario rechaza, "expirado" si
    se agota el tiempo, "red"/"http"/"respuesta" en los otros fallos.

    Usa time.sleep (bloqueante): esta variante es para consola y tests (que
    monkeypatchean sleep); la UI del panel usa el QTimer recurrente con
    `consultar_estado_dispositivo` por tick para no congelar Nuke.
    """
    cfg = config or vfxflow_config.obtener_config_efectiva()
    _validar_google_client_id(cfg)

    intervalo_actual = max(intervalo, 1)
    inicio = time.time()
    while time.time() - inicio < tiempo_maximo:
        time.sleep(intervalo_actual)
        resultado = consultar_estado_dispositivo(device_code, config=cfg)
        if resultado["estado"] == "ok":
            return resultado["datos"]
        codigo = resultado.get("codigo")
        if codigo == "authorization_pending":
            continue
        if codigo == "slow_down":
            intervalo_actual += 5
            continue
        if codigo == "access_denied":
            raise VfxFlowAuthError(
                "Inicio de sesión con Google denegado.", codigo="denegado"
            )
        raise VfxFlowAuthError(
            "Google respondió con un error en el flujo de dispositivo (%s)."
            % codigo,
            codigo="http",
        )
    raise VfxFlowAuthError(
        "Se agotó el tiempo para autorizar el dispositivo en Google.",
        codigo="expirado",
    )


# --------------------------------------------------------------------------
# Continuar con Google (OAuth 2.0 de escritorio: loopback redirect + PKCE)
# --------------------------------------------------------------------------

# Alfabeto permitido por la RFC 7636 (PKCE) para el code_verifier.
_ALFABETO_PKCE = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)
# Longitud del code_verifier (rango valido de la RFC 7636: 43 a 128 chars).
_LONGITUD_VERIFIER = 64

# Pagina que devuelve el mini server local al recibir el callback de Google.
_TEXTO_OK_LOOPBACK = (
    "<html><body><h3>Ya podés cerrar esta pestaña y volver a Nuke.</h3>"
    "</body></html>"
)


def generar_pkce():
    """Genera el par (code_verifier, code_challenge) para PKCE con S256.

    `code_verifier` es un string aleatorio criptografico de 43-128 chars del
    alfabeto `[A-Za-z0-9-._~]`. `code_challenge` es el SHA256 del verifier
    codificado en base64url SIN padding (metodo S256).

    Devuelve una tupla (verifier, challenge) de str.
    """
    verifier = "".join(
        secrets.choice(_ALFABETO_PKCE) for _ in range(_LONGITUD_VERIFIER)
    )
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def construir_url_autorizacion(client_id, redirect_uri, code_challenge, state=""):
    """Arma la URL de autorizacion de Google para el flujo de escritorio.

    Parametros del authorization code flow (Google OAuth 2.0 for installed
    apps): client_id, redirect_uri (`http://127.0.0.1:<puerto>`, el loopback
    que Google acepta sin configurar en clients "Desktop app"),
    response_type=code, scope "email profile openid" (el scope openid hace
    que el token endpoint devuelva el id_token de Google, que es el que se
    canjea en Firebase), code_challenge y code_challenge_method=S256.
    `state` es opcional (anti-CSRF) y solo se incluye si se pasa.
    """
    parametros = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "email profile openid",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if state:
        parametros["state"] = state
    return URL_AUTORIZACION + "?" + urllib.parse.urlencode(parametros)


class _HandlerLoopback(http.server.BaseHTTPRequestHandler):
    """Handler del callback loopback: captura code/error y apaga el server.

    Google redirige el navegador a `http://127.0.0.1:<puerto>/?code=...` (o
    con `error` si el usuario denego). do_GET guarda eso en
    `self.server.resultado`, responde la pagina "ya podes cerrar" y dispara
    `self.server.cerrar()`. `log_message` se anula para no ensuciar stdout.
    """

    def do_GET(self):
        params = urllib.parse.parse_qs(
            urllib.parse.urlparse(self.path).query
        )
        resultado = {}
        if "code" in params:
            resultado["code"] = params["code"][0]
        if "error" in params:
            resultado["error"] = params["error"][0]
        self.server.resultado = resultado

        cuerpo = _TEXTO_OK_LOOPBACK.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)
        self.server.cerrar()

    def log_message(self, formato, *args):
        # No ensuciar stdout de Nuke con los logs del mini server local.
        pass


class _ServidorLoopback(http.server.HTTPServer):
    """Mini server HTTP local (127.0.0.1, puerto aleatorio) del callback.

    `resultado` es un dict que el handler completa con {"code": ...} y/o
    {"error": ...}; empieza vacio. `cerrar()` lo apaga de forma segura desde
    cualquier hilo: `HTTPServer.shutdown()` NO puede llamarse desde el hilo
    que corre `serve_forever` (el mismo que ejecuta do_GET) porque se
    deadlockearia esperando el is_shut_down; por eso se dispara en un hilo
    daemon aparte.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.resultado = {}
        self._cerrado = False

    def cerrar(self):
        """Apaga el servidor sin bloquear al hilo que lo llama (idempotente).

        El handler, la espera bloqueante y la UI del panel lo llaman desde
        hilos distintos; la segunda llamada es no-op.
        """
        if self._cerrado:
            return
        self._cerrado = True
        threading.Thread(target=self._apagar, daemon=True).start()

    def _apagar(self):
        try:
            self.shutdown()
        finally:
            self.server_close()


def crear_servidor_loopback():
    """Crea el mini server HTTP local y devuelve (servidor, puerto).

    Escucha en 127.0.0.1 con puerto aleatorio (0 => lo asigna el SO). Ese
    puerto es el `redirect_uri` de la autorizacion
    (`http://127.0.0.1:<puerto>`), que Google acepta en clients de
    escritorio sin configurarlo explicitamente. El llamador es responsable de
    correr `serve_forever` en un thread daemon y de cerrar el servidor.
    """
    servidor = _ServidorLoopback(("127.0.0.1", 0), _HandlerLoopback)
    puerto = servidor.server_address[1]
    return servidor, puerto


def esperar_resultado_loopback(servidor, tiempo_maximo=300):
    """Espera (BLOQUEANTE) el code/error del callback loopback.

    Hace polling de `servidor.resultado` con `time.sleep(0.1)` hasta obtener
    code/error o agotar `tiempo_maximo`. Si no llega, cierra el servidor y
    devuelve {"error": "timeout"}.

    NO debe usarse desde la UI del panel: esa usa el QTimer recurrente con
    `_poll_loopback` para no congelar Nuke. Esta variante es para tests,
    consola y scripts.
    """
    inicio = time.time()
    while time.time() - inicio < tiempo_maximo:
        if servidor.resultado:
            return servidor.resultado
        time.sleep(0.1)
    servidor.cerrar()
    return {"error": "timeout"}


def canjear_codigo_autorizacion(
    code, redirect_uri, code_verifier, client_id, config=None
):
    """Canjea el code de autorizacion por tokens de Google (paso 5 OAuth).

    POST form-urlencoded al token endpoint con client_id, code, code_verifier,
    grant_type=authorization_code y redirect_uri (debe coincidir EXACTO con el
    usado en la URL de autorizacion). Devuelve:
        {"id_token", "refresh_token", "access_token", "expires_in"}
    El id_token de Google (requiere el scope openid) es el que despues se
    canjea en Firebase con `loguear_con_google`. El refresh_token de GOOGLE
    se usa una sola vez dentro del flujo y NUNCA se persiste.
    """
    cfg = config or vfxflow_config.obtener_config_efectiva()
    if not code or not code_verifier:
        raise VfxFlowAuthError(
            "Falta el código de autorización para canjear.", codigo="respuesta"
        )

    respuesta = _post_form(
        URL_GOOGLE_TOKEN,
        {
            "client_id": client_id,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
    )
    if respuesta["estado"] == "error":
        raise VfxFlowAuthError(
            "Google rechazó el canje del código de autorización (%s)."
            % respuesta["codigo"],
            codigo="http",
        )
    datos = respuesta["datos"]
    try:
        return {
            "id_token": datos["id_token"],
            "refresh_token": datos["refresh_token"],
            "access_token": datos["access_token"],
            "expires_in": datos["expires_in"],
        }
    except (KeyError, TypeError):
        raise VfxFlowAuthError(
            "Google respondió sin el id_token esperado.", codigo="respuesta"
        )


def obtener_client_id_escritorio(config=None):
    """Valida y devuelve `google_client_id_escritorio` de la config.

    El client "Desktop app" habilita el loopback redirect con PKCE (el flujo
    de escritorio preferido por UX). Si no esta configurado lanza
    VfxFlowAuthError codigo "config" con instrucciones para crearlo.
    """
    cfg = config or vfxflow_config.obtener_config_efectiva()
    client_id = (cfg or {}).get("google_client_id_escritorio", "")
    if not client_id:
        raise VfxFlowAuthError(
            "Falta google_client_id_escritorio en la config (crea un OAuth "
            "client tipo 'Desktop app' y agregalo a .saman/vfxflow_config.json "
            "o config_local.py).",
            codigo="config",
        )
    return client_id


def loguear_con_google(id_token_google, config=None):
    """Canjea el id_token de GOOGLE por una sesion de VFXFlow (Firebase).

    signInWithIdp convierte el id_token de Google (del Device Flow) en
    credenciales de Firebase, con el MISMO formato que `loguear`.
    Devuelve: {"id_token", "refresh_token", "expires_in", "local_id", "email"}
    (refresh_token es el de FIREBASE, el unico que se persiste).
    """
    cfg = config or vfxflow_config.obtener_config_efectiva()
    if not id_token_google:
        raise VfxFlowAuthError(
            "No se recibió el id_token de Google.", codigo="respuesta"
        )

    url = URL_SIGN_IN_IDP.format(api_key=cfg[_API_KEY_CAMPO])
    payload = {
        "postBody": "id_token={0}&providerId=google.com".format(id_token_google),
        "requestUri": "http://localhost",
        "returnSecureToken": True,
    }
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
    cfg = config or vfxflow_config.obtener_config_efectiva()
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
    cfg = config or vfxflow_config.obtener_config_efectiva()
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