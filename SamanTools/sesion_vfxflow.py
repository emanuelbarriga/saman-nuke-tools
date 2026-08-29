"""
SamanTools.sesion_vfxflow - Persistencia segura del refresh token de VFXFlow.

El refresh_token es un credential de larga vida: se persiste en disco local
con permisos restringidos (0600 en POSIX) para que solo el usuario pueda
leerlo. El dict persistido se LIMITA a {refresh_token, local_id, email}:
el id_token (1 hora) y la password NUNCA se guardan.

Todas las funciones son totales: devuelven True/None ante cualquier error y
nunca lanzan, para no romper la UI de Nuke.
"""

import json
import os

# Ruta del archivo de sesion (monkeypateable en tests).
_RUTA = os.path.expanduser("~/.config/saman/vfxflow_sesion.json")

# Claves que se persisten (el resto de la sesion en memoria se descarta).
_CLAVES_PERSISTIDAS = ("refresh_token", "local_id", "email")


def ruta_sesion():
    """Devuelve la ruta absoluta del archivo de sesion de VFXFlow."""
    return _RUTA


def guardar_sesion(sesion):
    """Guarda la sesion (limitada a refresh_token/local_id/email) en disco.

    Crea `~/.config/saman/` si falta y aplica permisos 0600 en POSIX.
    Devuelve True si se escribio, False ante cualquier fallo. Nunca lanza.
    """
    try:
        datos = {}
        for clave in _CLAVES_PERSISTIDAS:
            if clave in sesion:
                datos[clave] = sesion[clave]

        directorio = os.path.dirname(_RUTA)
        if directorio:
            os.makedirs(directorio, exist_ok=True)

        with open(_RUTA, "w", encoding="utf-8") as fh:
            json.dump(datos, fh, ensure_ascii=False, indent=2)

        if os.name == "posix":
            os.chmod(_RUTA, 0o600)
        return True
    except Exception:
        return False


def cargar_sesion():
    """Lee y parsea el archivo de sesion.

    Devuelve el dict guardado, o None si el archivo no existe / esta roto.
    Nunca lanza.
    """
    try:
        with open(_RUTA, "r", encoding="utf-8") as fh:
            datos = json.load(fh)
        if not isinstance(datos, dict):
            return None
        return datos
    except Exception:
        return None


def borrar_sesion():
    """Elimina el archivo de sesion si existe.

    Devuelve True si se borro, False si no existia o fallo. Nunca lanza.
    """
    try:
        if os.path.exists(_RUTA):
            os.remove(_RUTA)
            return True
        return False
    except Exception:
        return False