"""
Datos del nodo Breakdown: filas de frames, mascara de capas y plan del grafo.

Este modulo NO importa Nuke ni Qt a proposito: asi la logica se puede probar
con pytest fuera de Nuke y el widget (`frame_manager.py`) se apoya en el.

Storage tipado en el grupo (`nodos/Breakdown.gizmo`), todo invisible:

    N            Int_Knob  cantidad de filas (1..POOL)
    F_<i>        Int_Knob  frame de la fila i
    L_<i>        Int_Knob  mascara de capas de la fila i (bits 1, 2, 4, 8, 16)
    frame_data   String    JSON legacy: solo se lee para migrar una unica vez

Los knobs son nativos (Int), no un blob JSON: editar una celda escribe como
maximo los dos knobs de esa fila y no re-serializa la tabla entera.
"""

import json
import math
import unicodedata

#: Capas visuales, en el orden de las columnas de la tabla. Fijas por diseno.
CAPAS = ("brillo", "muzzle", "humo", "impacto", "sangre")

#: Mapa capa -> bit dentro del knob `L_<i>`.
BITS = {nombre: 1 << indice for indice, nombre in enumerate(CAPAS)}

#: Mascara con todas las capas encendidas (31 = 1+2+4+8+16).
MASCARA_MAX = (1 << len(CAPAS)) - 1

#: Filas maximas que el `.gizmo` declara. Mantener sincronizado con el gizmo.
POOL = 32

#: Knob con la cantidad de filas.
KNOB_FILAS = "N"

#: Knob del JSON legacy.
KNOB_LEGACY = "frame_data"

#: Knob con la version del formato ya migrado.
KNOB_VERSION = "datos_ver"

#: Version de storage: 1 = filas tipadas; 2 = columnas configurables.
VERSION_DATOS = 2

#: Tipos de columna admitidos, en el orden del knob Enumeration del `.gizmo`.
TIPOS = ("tilde", "texto", "numero")

#: Columnas maximas. 8 es el techo del pool de knobs de la pestana Columnas.
MAX_COLUMNAS = 8

#: Mascara con todas las columnas de tilde encendidas (hasta 8 columnas).
MASCARA_COLUMNAS = (1 << MAX_COLUMNAS) - 1

#: Knob con la cantidad de columnas de la tabla.
KNOB_COLUMNAS = "Cantidad"

#: Knob con los valores de las columnas de texto y numero.
KNOB_TEXTOS = "TXT"

#: Configuracion que usaban los comps anteriores a las columnas configurables.
COLUMNAS_CANONICAS = [
    {"nombre": nombre.capitalize(), "tipo": "tilde"} for nombre in CAPAS
]

#: Configuracion de un nodo nuevo: una columna de tilde y una de texto.
COLUMNAS_EJEMPLO = [
    {"nombre": "Muzzle", "tipo": "tilde"},
    {"nombre": "Nota", "tipo": "texto"},
]


def knob_frame(indice):
    """Nombre del knob Int con el frame de la fila `indice` (1..POOL)."""
    return "F_%d" % indice


def knob_capas(indice):
    """Nombre del knob Int con la mascara de tildes de la fila `indice`."""
    return "L_%d" % indice


def knob_col_nombre(slot):
    """Nombre del knob String con el nombre de la columna `slot`."""
    return "Col_%d_nombre" % slot


def knob_col_tipo(slot):
    """Nombre del knob Enumeration con el tipo de la columna `slot`."""
    return "Col_%d_tipo" % slot


def bit_de_columna(slot):
    """Bit de la mascara que corresponde a la columna `slot` (1..8)."""
    return 1 << (int(slot) - 1)


# ------------------------------------------------------------------ capas


def codificar_capas(estados):
    """Convierte `{capa: bool}` (o una fila legacy) en una mascara entera."""
    mascara = 0
    for nombre, bit in BITS.items():
        if estados.get(nombre):
            mascara |= bit
    return mascara


def decodificar_capas(mascara):
    """Convierte una mascara entera en `{capa: bool}` con las cinco capas.

    Los bits desconocidos se descartan y los conocidos se conservan, para que
    una mascara de una version futura no rompa la tabla.
    """
    try:
        mascara = int(mascara) & MASCARA_MAX
    except (TypeError, ValueError):
        mascara = 0
    return {nombre: bool(mascara & bit) for nombre, bit in BITS.items()}


def normalizar_frame(valor):
    """Devuelve un frame entero; cualquier valor invalido cae a 0."""
    try:
        return int(round(float(valor)))
    except (TypeError, ValueError):
        return 0


# ----------------------------------------------------------------- grilla


def grilla(cantidad):
    """Devuelve `(columnas, filas)` de la grilla mas cuadrada que los contenga.

    Con cero o un frame devuelve `(1, 1)`; el ContactSheet necesita al menos
    una celda para evaluar sus dimensiones.
    """
    cantidad = max(0, int(cantidad))
    if cantidad <= 1:
        return (1, 1)
    columnas = int(math.ceil(math.sqrt(cantidad)))
    filas = int(math.ceil(cantidad / float(columnas)))
    return (columnas, filas)


# --------------------------------------------------------- reconciliacion


def plan_reconciliacion(deseados, existentes):
    """Decide que indices del grafo interno reusar, crear y borrar.

    `deseados` es la cantidad de filas de la tabla; `existentes` son los
    indices (1..N) de los que ya tienen FrameHold/Text en el grupo. Reusar lo
    que ya esta evita borrar y recrear el grafo en cada Generar.
    """
    deseados = set(range(1, max(0, int(deseados)) + 1))
    existentes = set(existentes or ())
    return {
        "reusar": sorted(deseados & existentes),
        "crear": sorted(deseados - existentes),
        "sobrantes": sorted(existentes - deseados),
    }


# ------------------------------------------------------- modelo de columnas


def normalizar_tipo(valor):
    """Devuelve `tilde`, `texto` o `numero` a partir de la etiqueta del knob.

    El knob es un Enumeration con las etiquetas `Tilde`, `Texto` y `Numero`;
    cualquier valor inesperado cae a `tilde`.
    """
    if not isinstance(valor, str):
        return "tilde"
    limpio = unicodedata.normalize("NFKD", valor)
    limpio = limpio.encode("ascii", "ignore").decode("ascii").strip().lower()
    return limpio if limpio in TIPOS else "tilde"


def normalizar_columnas(columnas):
    """Completa nombres vacios y recorta/padea al maximo de columnas."""
    resultado = []
    for indice in range(1, MAX_COLUMNAS + 1):
        columna = columnas[indice - 1] if indice <= len(columnas) else {}
        if not isinstance(columna, dict):
            columna = {}
        nombre = str(columna.get("nombre", "") or "").strip()
        resultado.append(
            {
                "nombre": nombre or "Columna %d" % indice,
                "tipo": normalizar_tipo(columna.get("tipo", "tilde")),
            }
        )
    return resultado


def leer_columnas(nodo):
    """Configuracion de columnas del nodo, ya normalizada y recortada."""
    cantidad = normalizar_frame(_valor(nodo, KNOB_COLUMNAS, 0))
    cantidad = max(0, min(cantidad, MAX_COLUMNAS))
    columnas = []
    for slot in range(1, cantidad + 1):
        columnas.append(
            {
                "nombre": str(_valor(nodo, knob_col_nombre(slot), "") or "").strip()
                or "Columna %d" % slot,
                "tipo": normalizar_tipo(_valor(nodo, knob_col_tipo(slot), "Tilde")),
            }
        )
    return columnas


def escribir_columnas(nodo, columnas):
    """Escribe `Cantidad` y los knobs de nombre/tipo de cada slot.

    Limpia los slots que quedaron fuera de la cantidad nueva, para que un
    Enumeration o un nombre viejo no confunda a la proxima lectura.
    """
    columnas = list(columnas)[:MAX_COLUMNAS]
    _escribir_numero(nodo, KNOB_COLUMNAS, len(columnas))

    for slot in range(1, MAX_COLUMNAS + 1):
        columna = columnas[slot - 1] if slot <= len(columnas) else None
        if columna is None:
            _escribir_texto(nodo, knob_col_nombre(slot), "")
            _escribir_texto(nodo, knob_col_tipo(slot), "Tilde")
            continue
        normal = normalizar_columnas([columna])[0]
        _escribir_texto(nodo, knob_col_nombre(slot), normal["nombre"])
        _escribir_texto(nodo, knob_col_tipo(slot), normal["tipo"].capitalize())


# ------------------------------------------------- valores de texto/numero


def leer_textos(nodo):
    """Valores de las columnas de texto/numero: `{fila: {slot: str}}`.

    Un `TXT` vacio, corrupto o con una forma inesperada devuelve `{}` sin
    lanzar excepcion: la tabla arranca sin textos y no se pierde nada mas.
    """
    crudo = _valor(nodo, KNOB_TEXTOS, "")
    if not crudo:
        return {}
    try:
        crudo = json.loads(crudo)
    except (TypeError, ValueError):
        return {}
    if not isinstance(crudo, dict):
        return {}

    textos = {}
    for fila, valores in crudo.items():
        if not isinstance(valores, dict):
            continue
        limpios = {}
        for slot, valor in valores.items():
            if valor in (None, ""):
                continue
            limpios[normalizar_frame(slot)] = str(valor)
        if limpios:
            textos[normalizar_frame(fila)] = limpios
    return textos


def escribir_textos(nodo, textos):
    """Serializa los textos omitiendo vacios y sin reescribir si no cambio."""
    limpios = {}
    for fila in sorted(textos or {}):
        valores = textos[fila] or {}
        fila_limpia = {
            str(normalizar_frame(slot)): str(valor)
            for slot, valor in valores.items()
            if valor not in (None, "")
        }
        if fila_limpia:
            limpios[str(normalizar_frame(fila))] = fila_limpia

    texto = json.dumps(limpios, sort_keys=True) if limpios else ""
    _escribir_texto(nodo, KNOB_TEXTOS, texto)


def valor_celda(fila, textos, indice, slot, tipo):
    """Valor de una celda segun el tipo de su columna.

    Los tildes salen de la mascara de la fila; texto y numero, de `textos`.
    """
    tipo = normalizar_tipo(tipo)
    if tipo == "tilde":
        mascara = normalizar_frame(fila.get("capas", 0))
        return bool(mascara & bit_de_columna(slot))
    return (textos.get(normalizar_frame(indice)) or {}).get(normalizar_frame(slot), "")


def escribir_celda(nodo, indice, slot, valor):
    """Escribe una sola celda. Camino caliente de la tabla.

    Un booleano va a la mascara `L_<i>` (un solo knob); cualquier otro valor
    va al `TXT` compartido, que se reescribe entero pero solo al confirmar.
    """
    indice = normalizar_frame(indice)
    slot = normalizar_frame(slot)
    if not (1 <= indice <= POOL and 1 <= slot <= MAX_COLUMNAS):
        return

    if isinstance(valor, bool):
        mascara = normalizar_frame(_valor(nodo, knob_capas(indice), 0))
        bit = bit_de_columna(slot)
        nueva = (mascara | bit) if valor else (mascara & ~bit)
        _escribir_numero(nodo, knob_capas(indice), nueva & MASCARA_COLUMNAS)
        return

    textos = leer_textos(nodo)
    fila = dict(textos.get(indice) or {})
    texto = "" if valor is None else str(valor)
    if texto == "":
        fila.pop(slot, None)
    else:
        fila[slot] = texto
    if fila:
        textos[indice] = fila
    else:
        textos.pop(indice, None)
    escribir_textos(nodo, textos)


# --------------------------------------------------------------- legacy


def filas_desde_legacy(texto):
    """Convierte el JSON viejo (`frame_data`) en filas del storage tipado.

    Acepta solo una lista de objetos; un texto vacio, un JSON corrupto o una
    estructura inesperada devuelven una lista vacia sin lanzar excepcion.
    No recorta al pool: quien decide que hacer con el excedente es la
    migracion, que conserva el JSON como respaldo.
    """
    if not texto:
        return []
    try:
        crudo = json.loads(texto)
    except (TypeError, ValueError):
        return []
    if not isinstance(crudo, list):
        return []

    filas = []
    for fila in crudo:
        if not isinstance(fila, dict):
            continue
        filas.append(
            {
                "frame": normalizar_frame(fila.get("frame", 0)),
                "capas": codificar_capas(fila),
            }
        )
    return filas


# ------------------------------------------------------------ I/O de nodo
#
# Estas funciones solo usan `nodo.knobs()`, `knob.value()` y
# `knob.setValue()`: sirven con un nodo de Nuke y con un doble de prueba.


def _knob(nodo, nombre):
    try:
        return nodo.knobs().get(nombre)
    except Exception:
        return None


def _valor(nodo, nombre, defecto=0):
    knob = _knob(nodo, nombre)
    if knob is None:
        return defecto
    try:
        return knob.value()
    except Exception:
        return defecto


def _escribir_numero(nodo, nombre, valor):
    """Escribe un knob Int solo si cambia; evita ruido en el undo."""
    knob = _knob(nodo, nombre)
    if knob is None:
        return False
    valor = normalizar_frame(valor)
    try:
        if normalizar_frame(knob.value()) == valor:
            return False
    except Exception:
        pass
    knob.setValue(valor)
    return True


def _escribir_texto(nodo, nombre, valor):
    knob = _knob(nodo, nombre)
    if knob is None:
        return False
    try:
        if knob.value() == valor:
            return False
    except Exception:
        pass
    knob.setValue(valor)
    return True


def leer_filas(nodo):
    """Devuelve `[{"frame": int, "capas": int}, ...]` desde el storage tipado."""
    total = max(0, min(normalizar_frame(_valor(nodo, KNOB_FILAS, 0)), POOL))
    filas = []
    for indice in range(1, total + 1):
        filas.append(
            {
                "frame": normalizar_frame(_valor(nodo, knob_frame(indice), 0)),
                "capas": normalizar_frame(_valor(nodo, knob_capas(indice), 0))
                & MASCARA_COLUMNAS,
            }
        )
    return filas


def escribir_fila(nodo, indice, fila):
    """Escribe una sola fila. Camino caliente: editar una celda de la tabla."""
    _escribir_numero(nodo, knob_frame(indice), fila.get("frame", 0))
    _escribir_numero(
        nodo, knob_capas(indice), int(fila.get("capas", 0)) & MASCARA_COLUMNAS
    )


def escribir_filas(nodo, filas):
    """Escribe todas las filas y limpia los slots que quedaron sin uso."""
    filas = list(filas)[:POOL]
    previo = min(normalizar_frame(_valor(nodo, KNOB_FILAS, 0)), POOL)

    _escribir_numero(nodo, KNOB_FILAS, len(filas))
    for indice, fila in enumerate(filas, 1):
        escribir_fila(nodo, indice, fila)

    for indice in range(len(filas) + 1, max(previo, len(filas)) + 1):
        _escribir_numero(nodo, knob_frame(indice), 0)
        _escribir_numero(nodo, knob_capas(indice), 0)


def legacy_parseable(texto):
    """True si `texto` es un JSON con forma de lista de filas."""
    if not texto:
        return False
    try:
        crudo = json.loads(texto)
    except (TypeError, ValueError):
        return False
    return isinstance(crudo, list)


def migrar_legacy(nodo):
    """Lleva el nodo a `VERSION_DATOS`, sin perder nada por el camino.

    Ramas (S17):

    * `datos_ver` ausente / 0 con `frame_data` parseable: comp del gizmo
      original. Se vuelcan las filas y se instalan las 5 columnas canonicas
      (sus mascaras ya usan los mismos bits). Si el legacy no entra entero en
      el pool, el texto original queda intacto como respaldo.
    * `datos_ver` ausente / 0 sin legacy: nodo nuevo. No se toca nada: se
      respetan las columnas de ejemplo y las filas que shipea el `.gizmo`.
    * `datos_ver` 1: comps de la version intermedia, con las 5 capas fijas en
      las mascaras. Se instalan las columnas canonicas y no se tocan filas.
    * `datos_ver` >= 2: nada.

    Devuelve True si escribio algo.
    """
    version = normalizar_frame(_valor(nodo, KNOB_VERSION, 0))
    if version >= VERSION_DATOS:
        return False

    cambio = False
    if version == 0:
        texto = _valor(nodo, KNOB_LEGACY, "")
        if legacy_parseable(texto):
            filas = filas_desde_legacy(texto)
            escribir_filas(nodo, filas)
            escribir_columnas(nodo, COLUMNAS_CANONICAS)
            cambio = True
            if len(filas) <= POOL:
                _escribir_texto(nodo, KNOB_LEGACY, "")
    elif version == 1:
        escribir_columnas(nodo, COLUMNAS_CANONICAS)
        cambio = True

    _escribir_numero(nodo, KNOB_VERSION, VERSION_DATOS)
    return cambio


def legacy_excedente(nodo):
    """Filas del legacy que no entran en el pool (0 si entran todas).

    Se consulta despues de `migrar_legacy` para avisar al artista cuando el
    JSON original quedo conservado como respaldo.
    """
    return max(0, len(filas_desde_legacy(_valor(nodo, KNOB_LEGACY, ""))) - POOL)
