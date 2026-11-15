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

#: Version de storage tipado. Un nodo con `datos_ver` >= esta ya no migra.
VERSION_DATOS = 1


def knob_frame(indice):
    """Nombre del knob Int con el frame de la fila `indice` (1..POOL)."""
    return "F_%d" % indice


def knob_capas(indice):
    """Nombre del knob Int con la mascara de capas de la fila `indice`."""
    return "L_%d" % indice


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
                & MASCARA_MAX,
            }
        )
    return filas


def escribir_fila(nodo, indice, fila):
    """Escribe una sola fila. Camino caliente: editar una celda de la tabla."""
    _escribir_numero(nodo, knob_frame(indice), fila.get("frame", 0))
    _escribir_numero(
        nodo, knob_capas(indice), int(fila.get("capas", 0)) & MASCARA_MAX
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


def migrar_legacy(nodo):
    """Vuelca el JSON legacy al storage tipado una unica vez.

    Devuelve True si migro algo. La marca de "ya migrado" es el knob
    `datos_ver`, no el contenido del legacy: asi un JSON que no entra entero
    en el pool puede quedarse como respaldo sin volver a migrarse (y sin
    pisar lo que el artista edite despues).

    Si el legacy tiene mas filas que `POOL` se migran las que entran y el
    texto original se conserva intacto: nada se pierde en silencio.
    """
    if normalizar_frame(_valor(nodo, KNOB_VERSION, 0)) >= VERSION_DATOS:
        return False

    filas = filas_desde_legacy(_valor(nodo, KNOB_LEGACY, ""))
    migrado = False
    if filas:
        escribir_filas(nodo, filas)
        migrado = True
        if len(filas) <= POOL:
            _escribir_texto(nodo, KNOB_LEGACY, "")

    _escribir_numero(nodo, KNOB_VERSION, VERSION_DATOS)
    return migrado


def legacy_excedente(nodo):
    """Filas del legacy que no entran en el pool (0 si entran todas).

    Se consulta despues de `migrar_legacy` para avisar al artista cuando el
    JSON original quedo conservado como respaldo.
    """
    return max(0, len(filas_desde_legacy(_valor(nodo, KNOB_LEGACY, ""))) - POOL)
