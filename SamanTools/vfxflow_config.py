"""
SamanTools.vfxflow_config - Config publica del cliente REST de VFXFlow.

VFXFlow es la app web (proyecto Firebase `vfxpm-be912`) que administra los
planos del estudio. Este panel de Nuke se conecta a su backend igual que el
navegador: la config de Firebase de una app web vive en su bundle JS y es
PUBLICA por diseno (modelo de Firebase: la seguridad real la dan las Firebase
Rules + la autenticacion, NO la api key). Por eso estos valores estan
versionados.

    api_key         key de la app Firebase (publica por diseno).
    project_id      id del proyecto Firebase (vfxpm-be912).
    auth_domain     dominio de autenticacion email/password.
    storage_bucket  bucket de almacenamiento (no usado en v1, por completitud).
    google_client_id  client_id OAuth de Google para "Continuar con Google"
                      (Device Flow). Es PUBLICO por diseno (viaja en el
                      bundle JS de cualquier app web; el secreto real de una
                      OAuth app es el client_secret, que aca NO se usa). Se
                      crea en Google Cloud Console > APIs & Services >
                      Credentials > Create Credentials > OAuth client ID >
                      "TVs and Limited Input devices".
    google_client_id_escritorio
                      client_id OAuth tipo "Desktop app" (loopback redirect
                      con PKCE) para el flujo de escritorio de "Continuar con
                      Google". PUBLICO por diseno (en el OAuth de escritorio
                      el secreto real es el code_verifier de PKCE, no hay
                      client_secret). Si esta configurado, el panel lo usa con
                      prioridad por UX (no hay que tipear un codigo); si no,
                      cae al Device Flow. Se crea en Google Cloud Console >
                      APIs & Services > Credentials > Create Credentials >
                      OAuth client ID > "Desktop app".

Los google_client_id (ambos) se cargan en RUNTIME (prioridad; gana la
ultima):

    1. VFXFLOW_CONFIG: los defaults de arriba (client_id vacio hasta que el
       admin lo reparte).
    2. Archivo `.saman/vfxflow_config.json` en la raiz de la unidad wupm
       (base = SamanTools.entorno.primera_ruta_disponible()). Protegido por
       los ACL de LucidLink: solo el admin escribe, los artistas leen.
    3. `config_local.py` (gitignored) con un dict `VFXFLOW_LOCAL_CONFIG`:
       override local por-usuario.

El client_secret NUNCA va al repo ni al archivo del disco compartido: si
alguna vez hiciera falta un secreto de SERVICIO, ese va en config_local.py.
"""

import json
import os

VFXFLOW_CONFIG = {
    "api_key": "AIzaSyARni3zruIfFx7ZTmKq8bDPsCkH6nhP0Bo",
    "project_id": "vfxpm-be912",
    "auth_domain": "vfxpm-be912.firebaseapp.com",
    "storage_bucket": "vfxpm-be912.firebasestorage.app",
    # El client_id real se carga en runtime desde .saman/vfxflow_config.json
    # o config_local.py (ver docstring); el default queda vacio.
    "google_client_id": "",
    # Client OAuth tipo "Desktop app" (loopback redirect) para "Continuar con
    # Google" con PKCE; publico por diseno. Si esta configurado, el panel lo
    # usa con prioridad sobre el Device Flow (mejor UX). Crear en Google Cloud
    # Console > APIs & Services > Credentials > OAuth client ID > "Desktop app".
    "google_client_id_escritorio": "",
}

# Ruta {base}/.saman/vfxflow_config.json sobre la unidad wupm del estudio.
ARCHIVO_DISCO = ".saman/vfxflow_config.json"


def _cargar_config_disco():
    """Devuelve el dict JSON de {base}/.saman/vfxflow_config.json, o {}.

    La base la da `entorno.primera_ruta_disponible()` (import lazy para no
    acoplar este modulo a la deteccion de la unidad). Archivo ausente, no
    legible o con JSON invalido se ignoran en silencio: quedan los defaults.
    """
    mod_entorno = globals().get("entorno")
    if mod_entorno is None:
        try:
            from . import entorno as mod_entorno
        except (ImportError, AttributeError):
            return {}
        globals()["entorno"] = mod_entorno
    base = mod_entorno.primera_ruta_disponible(mod_entorno.detectar_so())
    if not base:
        return {}
    ruta = os.path.join(base, *ARCHIVO_DISCO.split("/"))
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            datos = json.load(f)
    except (FileNotFoundError, OSError, ValueError):
        return {}
    if not isinstance(datos, dict):
        return {}
    return datos


def _cargar_config_local():
    """Devuelve `VFXFLOW_LOCAL_CONFIG` de config_local.py, o {}.

    config_local.py es un modulo gitignored del paquete ("from SamanTools
    import config_local"): override local por-usuario, jamas versionado.
    Un ImportError (modulo ausente) o un dict ausente se ignoran en silencio.
    """
    try:
        from SamanTools import config_local
    except (ImportError, AttributeError):
        return {}
    local = getattr(config_local, "VFXFLOW_LOCAL_CONFIG", None)
    if not isinstance(local, dict):
        return {}
    return local


def obtener_config_efectiva():
    """Config fusionada: defaults + disco + config_local. Gana la ultima.

    Prioridad:
        1. VFXFLOW_CONFIG (defaults versionados).
        2. `.saman/vfxflow_config.json` en la raiz de la unidad wupm
           (protegido por ACL de LucidLink; lo escribe el admin).
        3. config_local.py (gitignored, dict VFXFLOW_LOCAL_CONFIG).

    Nunca lanza por config ausente: los fallos de lectura se ignoran.
    """
    config = dict(VFXFLOW_CONFIG)
    config.update(_cargar_config_disco())
    config.update(_cargar_config_local())
    return config