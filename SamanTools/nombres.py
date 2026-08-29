"""
SamanTools.nombres - Parseo de nombres de platos/planos VFX sin depender de
Nuke, para poder testearlo con pytest puro.

Convencion de nombres de plato canonico:

    {PROYECTO}_{EP}_{escena}_{shot}_V{nn}.mov

Ejemplo canonico:

    HTLR_107_008_00100_V01.mov
        proyecto = HTLR
        capitulo = 107
        escena   = "008"
        shot     = "00100"
        plano    = "008_00100"
        version  = "V01"

A veces el cliente escribe la version en el medio (nombre malformado); la
interpretacion correcta mueve la version al FINAL del nombre:

    HTLR_108_012_V01_0100.mov  ->  HTLR_108_012_0100_V01.mov
    HTLR_108_034_V01_0100.mov  ->  HTLR_108_034_0100_V01.mov

Los comps de Nuke agregan el sufijo de la empresa despues del plano y se
trata como METADATO (no forma parte del plano, pero se conserva en el
nombre canonico):

    HTLR_107_008_00100_comp_SAMAN_V01.nk
        plano  = "008_00100"  (comp y SAMAN no entran al plano)

Las referencias PNG no llevan version:

    HTLR_107_012_01500.png  ->  version None

El capitulo NO lleva prefijo 'EP_' dentro del filename (HTLR_107_...), pero
SI en la ruta de carpetas (TO_VFX/EP_107/...). Si la ruta contiene un
segmento 'EP_<digitos>', ese valor es autoritativo; si no, se usa el primer
token numerico despues del prefijo del proyecto en el filename.
"""

import os
import re

from .entorno import proyecto_desde_ruta

# Token de version: parte separada por '_' que matchea V seguido de digitos.
_REGEX_VERSION = re.compile(r"^[vV]\d+$")
# Segmento de carpeta que indica capitulo: EP_107, EP_110, ...
_REGEX_EP = re.compile(r"^EP_(\d+)$")


def _token_version(tokens):
    """Devuelve el primer token de la lista que parece version (ej. 'V01')."""
    for token in tokens:
        if _REGEX_VERSION.match(token):
            return token
    return None


def parsear_plato(ruta):
    """
    Parsea una ruta (o solo un basename) de plato/plano VFX y devuelve un
    dict con: proyecto, capitulo, escena, shot, plano, version, archivo,
    canonico y malformado.

    Devuelve None si la entrada esta vacia, si el basename no alcanza los
    4 tokens minimos (prefijo + capitulo + escena + shot) o si no hay un
    token numerico de capitulo despues del prefijo. Nunca lanza.
    """
    if ruta is None:
        return None
    ruta = str(ruta)
    if not ruta.strip():
        return None

    normalizada = ruta.replace("\\", "/")
    basename = os.path.basename(normalizada)
    if not basename:
        return None
    tallo, ext = os.path.splitext(basename)
    tokens = tallo.split("_")
    prefijo = tokens[0]

    # Minimo canonico: prefijo + capitulo + escena + shot (4 tokens).
    if len(tokens) < 4:
        return None

    version_token = _token_version(tokens)
    version = version_token.upper() if version_token else None

    # Capitulo autoritativo: cualquier carpeta 'EP_<digitos>' de la ruta.
    dir_part = normalizada.rsplit("/", 1)[0] if "/" in normalizada else ""
    capitulo_ruta_txt = None
    for componente in dir_part.split("/"):
        m = _REGEX_EP.match(componente)
        if m:
            capitulo_ruta_txt = m.group(1)
            break

    capitulo = None
    capitulo_para_nombre = None
    token_capitulo = tokens[1]
    if capitulo_ruta_txt is not None:
        capitulo = int(capitulo_ruta_txt)
        capitulo_para_nombre = capitulo_ruta_txt
    elif token_capitulo.isdigit():
        capitulo = int(token_capitulo)
        capitulo_para_nombre = token_capitulo
    else:
        # Sin capitulo: ni EP_ en la ruta ni token numerico tras el prefijo.
        return None

    # Escena/Shot: sobran el prefijo, el token de capitulo (posicional, sea
    # cual sea su valor) y la version. El token 'comp' es un LIMITE: marca
    # el inicio del sufijo de empresa del comp (ej. 'comp_SAMAN'), que es
    # metadato y NO forma parte del plano, aunque se conserva en canonico.
    resto = []
    sufijo_comp = []
    en_sufijo = False
    for idx, token in enumerate(tokens):
        if idx == 0 or idx == 1:
            continue
        if version_token is not None and token == version_token:
            continue
        if token == "comp":
            en_sufijo = True
            sufijo_comp.append(token)
            continue
        if en_sufijo:
            sufijo_comp.append(token)
        else:
            resto.append(token)

    if not resto:
        return None  # sin escena/shot que parsear (raro)

    escena = resto[0]
    shot = "_".join(resto[1:]) if len(resto) > 1 else None
    plano = "{0}_{1}".format(escena, shot) if (escena and shot) else None

    # Malformado: existe token de version pero NO es el ultimo token.
    malformado = bool(version_token) and tokens[-1] != version_token

    # Nombre corregido: la version SIEMPRE al final (si existe), y el
    # sufijo de empresa (comp_SAMAN) se conserva en su posicion original.
    canonico = None
    if escena and shot:
        partes = [prefijo, capitulo_para_nombre, escena, shot]
        partes.extend(sufijo_comp)
        if version:
            partes.append(version)
        canonico = "_".join(partes) + ext

    return {
        "proyecto": proyecto_desde_ruta(ruta),
        "capitulo": capitulo,
        "escena": escena,
        "shot": shot,
        "plano": plano,
        "version": version,
        "archivo": basename,
        "canonico": canonico,
        "malformado": malformado,
    }