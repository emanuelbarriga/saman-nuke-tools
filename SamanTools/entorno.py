"""
SamanTools.entorno - Deteccion del entorno de la matriz (LucidLink / wupm)
sin depender de Nuke, para poder testearla con pytest puro.

La matriz central monta LucidLink (disco virtual) en un servidor. Los
artistas solo montan la UNIDAD DE RED 'wupm' (SMB):

    macOS:    /Volumes/wupm/2026
    Windows:  L:/2026   (o la letra de unidad que tenga la carpeta 2026)
    Linux:    /mnt/wupm/2026

'estado_unidad()' responde con un timeout porque os.path.isdir() puede
colgarse en un mount SMB muerto (el kernel intenta reconectar). Un mount
colgado se considera DESCONECTADO.
"""

import os
import platform
import string
import subprocess
import time

# Timeout en segundos para la verificacion rapida via subprocess.
TIMEOUT_SEGUNDOS = 3

# Duracion de la cache a nivel de modulo: evita frenar la UI de Nuke
# con checks repetidos de los mismos mounts.
CACHE_SEGUNDOS = 10.0

# Cache por ruta base: { ruta: (timestamp, dict_estado) }.
_cache = {}

# Claves exactas de los knobs del nodo Rutas, por sufijo y subdirectorio.
SUFIJOS = ("MAC", "WINDOWS", "ARTIST")
PREFIJOS = ("TO_VFX", "comp", "FROM_VFX")


def detectar_so():
    """Devuelve 'macOS' | 'Windows' | 'Linux' segun platform.system()."""
    sistema = platform.system()
    if sistema == "Darwin":
        return "macOS"
    if sistema == "Windows":
        return "Windows"
    if sistema == "Linux":
        return "Linux"
    return sistema


def sufijo_so(so):
    """Sufijo de knob ('MAC'|'WINDOWS'|'ARTIST') compatible con *_SERVER_*."""
    return {"macOS": "MAC", "Windows": "WINDOWS", "Linux": "ARTIST"}.get(so, "ARTIST")


def usuario_activo(so):
    """Valor del knob UsuarioActivo ('MacServer'|'Windows'|'Artist')."""
    return {"macOS": "MacServer", "Windows": "Windows", "Linux": "Artist"}.get(so, "Artist")


def rutas_base(so, extra=None):
    """
    Rutas base candidatas (string/drive) en orden de preferencia.

    extra: ruta del usuario como candidata PRIORITARIA (va primera).
    """
    if so == "macOS":
        candidatas = ["/Volumes/wupm/2026", "/Volumes/wupmCloud/2026"]
    elif so == "Windows":
        candidatas = ["L:/2026"]
        for letra in string.ascii_uppercase:
            if letra == "L":
                continue
            ruta = letra + ":/2026"
            if os.path.isdir(ruta):
                candidatas.append(ruta)
    elif so == "Linux":
        candidatas = ["/mnt/wupm/2026"]
    else:
        candidatas = []

    if extra:
        if isinstance(extra, str):
            extra = [extra]
        # Ruta del usuario primero; sin duplicar las candidatas por defecto.
        candidatas = [e for e in extra if e] + [
            c for c in candidatas if c not in (extra or [])
        ]
    return candidatas


def _verificar_ruta(ruta):
    """
    Verifica que 'ruta' responda, con timeout real para no colgarse en
    un mount SMB muerto. En Windows usa dir; en POSIX ls -d.
    """
    sistema = detectar_so()
    if sistema == "Windows":
        cmd = ["cmd", "/c", "dir", ruta]
    else:
        cmd = ["ls", "-d", ruta]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=TIMEOUT_SEGUNDOS,
        )
    except subprocess.TimeoutExpired:
        # Mount colgado (el kernel intenta reconectar): se considera DESCONECTADO.
        return {
            "conectado": False,
            "ruta": None,
            "detalle": "Mount colgado (timeout {0}s).".format(TIMEOUT_SEGUNDOS),
        }
    except (FileNotFoundError, OSError):
        # Comando no disponible (entorno extraño): fallback a isdir.
        ok = os.path.isdir(ruta)
        return {
            "conectado": ok,
            "ruta": ruta if ok else None,
            "detalle": "Conectado." if ok else "No existe ({0}).".format(ruta),
        }

    if proc.returncode == 0:
        return {"conectado": True, "ruta": ruta, "detalle": "Conectado."}
    return {
        "conectado": False,
        "ruta": None,
        "detalle": "No existe ({0}).".format(ruta),
    }


def estado_unidad(ruta_base):
    """
    Devuelve {"conectado": bool, "ruta": str|None, "detalle": str}.

    Verificación RÁPIDA con timeout: una unidad SMB muerta NO se cuelga.
    Cache a nivel de módulo (~10s) para no frenar la UI de Nuke.
    """
    if not ruta_base or not str(ruta_base).strip():
        return {
            "conectado": False,
            "ruta": None,
            "detalle": "Ruta base vacia: configure 'Ruta Base' en el nodo.",
        }
    ruta = str(ruta_base).strip()

    ahora = time.time()
    if ruta in _cache:
        _ts, _res = _cache[ruta]
        if ahora - _ts < CACHE_SEGUNDOS:
            return _res

    res = _verificar_ruta(ruta)
    _cache[ruta] = (ahora, res)
    return res


def primera_ruta_disponible(so, extra=None):
    """Devuelve la primera ruta base de rutas_base() que responde, o None."""
    for ruta in rutas_base(so, extra):
        if estado_unidad(ruta)["conectado"]:
            return ruta
    return None


def reconstruir_rutas(ruta_base, proyecto):
    """
    Con {ruta_base} y {proyecto}, genera las 9 rutas del nodo Rutas:

        {base}/{proyecto}/TO_VFX/   + TO_VFX_SERVER_<SUF>
        {base}/{proyecto}/COMP/     + comp_SERVER_<SUF>
        {base}/{proyecto}/FROM_VFX/ + FROM_VFX_SERVER_<SUF>

    con SUF en (MAC, WINDOWS, ARTIST) y forward slashes SIEMPRE.
    """
    base = str(ruta_base).strip().rstrip("/\\")
    proy = str(proyecto).strip().strip("/\\")

    rutas = {}
    for suf in SUFIJOS:
        for pre in PREFIJOS:
            rutas[pre + "_SERVER_" + suf] = (
                base + "/" + proy + "/" + pre.upper() + "/"
            )
    return rutas


def proyecto_desde_ruta(ruta, base=None, so=None):
    """
    Identifica el proyecto a partir de la ruta de un archivo bajo la matriz.

    El proyecto es la PRIMERA carpeta bajo la base del anio:

        {base}/HTLR/COMP/EP_100/foo.nk  ->  "HTLR"

    Si {base} se omite, prueba con las candidatas de rutas_base(so)
    (default: el SO detectado). Devuelve None si la ruta no cae bajo
    ninguna base o si no hay carpeta de proyecto.
    """
    ruta = str(ruta or "").replace("\\", "/")
    ruta = ruta.rstrip("/") if ruta.strip() else ""
    if not ruta:
        return None

    if base is None:
        bases = rutas_base(so or detectar_so())
    else:
        bases = [base]

    for b in bases:
        b = str(b).replace("\\", "/").rstrip("/")
        if not b:
            continue
        if ruta == b:
            continue  # la ruta ES la base: no hay carpeta de proyecto
        if not ruta.startswith(b + "/"):
            continue  # no cae bajo esta base (evita prefijos parciales)
        resto = ruta[len(b) + 1:]
        partes = [p for p in resto.split("/") if p]
        if partes:
            return partes[0]
    return None