"""
Tests de `SamanTools/breakdown_datos.py`.

Cubren la lógica que decide qué se guarda en el nodo Breakdown y qué nodos del
grafo interno hay que crear, reusar o borrar. Corren fuera de Nuke: las
funciones de I/O sólo usan `knob.value()` / `knob.setValue()`, así que un nodo
falso con knobs alcanza como doble de prueba.
"""

import json

import pytest

from SamanTools import breakdown_datos as datos


class KnobFalso(object):
    """Knob mínimo: valor numérico o de texto, sin expresiones."""

    def __init__(self, valor=0):
        self._valor = valor
        self.escrituras = 0

    def value(self):
        return self._valor

    def setValue(self, valor):
        self._valor = valor
        self.escrituras += 1


class NodoFalso(object):
    """Nodo mínimo con el contrato de knobs que usa breakdown_datos."""

    def __init__(self, **knobs):
        self._knobs = {nombre: KnobFalso(v) for nombre, v in knobs.items()}

    def knobs(self):
        return self._knobs

    def __getitem__(self, nombre):
        return self._knobs[nombre]

    def __contains__(self, nombre):
        return nombre in self._knobs


def _nodo_vacio():
    """Nodo con el pool completo del .gizmo, todo en cero."""
    knobs = {
        datos.KNOB_FILAS: 0,
        datos.KNOB_LEGACY: "",
        datos.KNOB_VERSION: 0,
    }
    for i in range(1, datos.POOL + 1):
        knobs[datos.knob_frame(i)] = 0
        knobs[datos.knob_capas(i)] = 0
    return NodoFalso(**knobs)


# --------------------------------------------------------------- capas


def test_mascara_de_capas_ida_y_vuelta_en_las_32_combinaciones():
    for mascara in range(datos.MASCARA_MAX + 1):
        estados = datos.decodificar_capas(mascara)
        assert datos.codificar_capas(estados) == mascara


def test_capas_mapean_a_bits_1_2_4_8_16():
    assert datos.BITS == {
        "brillo": 1,
        "muzzle": 2,
        "humo": 4,
        "impacto": 8,
        "sangre": 16,
    }


def test_codificar_ignora_claves_desconocidas_y_trata_ausentes_como_false():
    assert datos.codificar_capas({"brillo": True, "inventada": True}) == 1
    assert datos.codificar_capas({}) == 0


def test_decodificar_devuelve_las_cinco_capas_siempre():
    assert datos.decodificar_capas(0) == {
        "brillo": False,
        "muzzle": False,
        "humo": False,
        "impacto": False,
        "sangre": False,
    }
    assert datos.decodificar_capas(21) == {
        "brillo": True,
        "muzzle": False,
        "humo": True,
        "impacto": False,
        "sangre": True,
    }


def test_decodificar_descarta_bits_fuera_de_rango_y_conserva_los_conocidos():
    assert (
        datos.codificar_capas(datos.decodificar_capas(datos.MASCARA_MAX + 32))
        == datos.MASCARA_MAX
    )


# -------------------------------------------------------------- grilla


@pytest.mark.parametrize(
    "n, esperado",
    [
        (0, (1, 1)),
        (1, (1, 1)),
        (2, (2, 1)),
        (3, (2, 2)),
        (4, (2, 2)),
        (5, (3, 2)),
        (9, (3, 3)),
        (10, (4, 3)),
    ],
)
def test_grilla_cuadrada_por_arriba(n, esperado):
    assert datos.grilla(n) == esperado


# ------------------------------------------------------ reconciliación


def test_plan_reusa_todo_cuando_ya_existe():
    plan = datos.plan_reconciliacion(3, {1, 2, 3})
    assert plan == {"reusar": [1, 2, 3], "crear": [], "sobrantes": []}


def test_plan_crea_solo_los_faltantes():
    plan = datos.plan_reconciliacion(3, {1, 2})
    assert plan == {"reusar": [1, 2], "crear": [3], "sobrantes": []}


def test_plan_borra_solo_los_sobrantes():
    plan = datos.plan_reconciliacion(2, {1, 2, 3, 4})
    assert plan == {"reusar": [1, 2], "crear": [], "sobrantes": [3, 4]}


def test_plan_reconstruye_huecos_del_medio():
    plan = datos.plan_reconciliacion(3, {2, 3})
    assert plan == {"reusar": [2, 3], "crear": [1], "sobrantes": []}


def test_plan_con_cero_filas_borra_todo():
    plan = datos.plan_reconciliacion(0, {1, 2})
    assert plan == {"reusar": [], "crear": [], "sobrantes": [1, 2]}


# --------------------------------------------------------- migración


def test_legacy_vacio_o_inexistente_da_cero_filas():
    assert datos.filas_desde_legacy("") == []
    assert datos.filas_desde_legacy("[]") == []


def test_legacy_corrupto_no_rompe():
    assert datos.filas_desde_legacy("{no es json") == []
    assert datos.filas_desde_legacy('{"frame": 10}') == []


def test_legacy_convierte_capas_a_mascara():
    texto = json.dumps(
        [
            {"frame": 10, "brillo": True},
            {"frame": 20, "humo": True, "sangre": True},
            {"frame": 30},
        ]
    )
    assert datos.filas_desde_legacy(texto) == [
        {"frame": 10, "capas": 1},
        {"frame": 20, "capas": 20},
        {"frame": 30, "capas": 0},
    ]


def test_legacy_normaliza_frame_invalido_a_cero():
    texto = json.dumps([{"frame": "abc"}, {"frame": 12.6}])
    assert datos.filas_desde_legacy(texto) == [
        {"frame": 0, "capas": 0},
        {"frame": 13, "capas": 0},
    ]


# -------------------------------------------------------- I/O de filas


def test_escribir_y_leer_filas_es_ida_y_vuelta():
    nodo = _nodo_vacio()
    filas = [
        {"frame": 10, "capas": 1},
        {"frame": 20, "capas": 20},
        {"frame": 30, "capas": 0},
    ]
    datos.escribir_filas(nodo, filas)

    assert nodo[datos.KNOB_FILAS].value() == 3
    assert datos.leer_filas(nodo) == filas


def test_escribir_filas_limpia_los_slots_sobrantes():
    nodo = _nodo_vacio()
    datos.escribir_filas(
        nodo,
        [
            {"frame": 1, "capas": 1},
            {"frame": 2, "capas": 2},
            {"frame": 3, "capas": 3},
        ],
    )
    datos.escribir_filas(nodo, [{"frame": 1, "capas": 1}])

    assert nodo[datos.KNOB_FILAS].value() == 1
    assert datos.leer_filas(nodo) == [{"frame": 1, "capas": 1}]
    assert nodo[datos.knob_frame(2)].value() == 0
    assert nodo[datos.knob_capas(2)].value() == 0


def test_escribir_filas_recorta_al_tamano_del_pool():
    nodo = _nodo_vacio()
    filas = [{"frame": i, "capas": 0} for i in range(1, datos.POOL + 10)]
    datos.escribir_filas(nodo, filas)

    assert nodo[datos.KNOB_FILAS].value() == datos.POOL
    assert len(datos.leer_filas(nodo)) == datos.POOL


def test_leer_filas_ignora_un_contador_mayor_al_pool():
    nodo = _nodo_vacio()
    nodo[datos.KNOB_FILAS].setValue(datos.POOL + 5)
    assert len(datos.leer_filas(nodo)) == datos.POOL


def test_migrar_legacy_vuelca_y_blanquea():
    nodo = _nodo_vacio()
    nodo[datos.KNOB_LEGACY].setValue(
        json.dumps([{"frame": 10, "brillo": True}, {"frame": 20}])
    )

    assert datos.migrar_legacy(nodo) is True
    assert datos.leer_filas(nodo) == [
        {"frame": 10, "capas": 1},
        {"frame": 20, "capas": 0},
    ]
    assert nodo[datos.KNOB_LEGACY].value() == ""


def test_migrar_legacy_es_idempotente():
    nodo = _nodo_vacio()
    nodo[datos.KNOB_LEGACY].setValue(json.dumps([{"frame": 10}]))
    datos.migrar_legacy(nodo)

    assert datos.migrar_legacy(nodo) is False
    assert datos.leer_filas(nodo) == [{"frame": 10, "capas": 0}]


def test_migrar_legacy_no_toca_el_pool_si_el_json_esta_vacio():
    nodo = _nodo_vacio()
    datos.escribir_filas(nodo, [{"frame": 7, "capas": 5}])
    nodo[datos.KNOB_LEGACY].setValue("[]")

    assert datos.migrar_legacy(nodo) is False
    assert datos.leer_filas(nodo) == [{"frame": 7, "capas": 5}]


def test_migrar_legacy_versionado_no_escribe_ningun_knob():
    """S8: datos_ver evita una segunda migración sin ruido en el undo."""
    nodo = _nodo_vacio()
    nodo[datos.KNOB_VERSION]._valor = datos.VERSION_DATOS
    nodo[datos.KNOB_LEGACY]._valor = json.dumps([{"frame": 10}])

    assert datos.migrar_legacy(nodo) is False
    assert all(knob.escrituras == 0 for knob in nodo.knobs().values())


def test_migrar_legacy_corrupto_marca_version_y_conserva_storage_y_respaldo():
    """S8: un JSON corrupto no pisa filas tipadas ni se vuelve a intentar."""
    nodo = _nodo_vacio()
    datos.escribir_filas(nodo, [{"frame": 7, "capas": 5}])
    nodo[datos.KNOB_LEGACY]._valor = "{no es json"
    for knob in nodo.knobs().values():
        knob.escrituras = 0

    assert datos.migrar_legacy(nodo) is False
    assert datos.leer_filas(nodo) == [{"frame": 7, "capas": 5}]
    assert nodo[datos.KNOB_LEGACY].value() == "{no es json"
    assert nodo[datos.KNOB_VERSION].value() == datos.VERSION_DATOS
    assert nodo[datos.KNOB_VERSION].escrituras == 1
    assert all(
        nodo[datos.knob_frame(indice)].escrituras == 0
        and nodo[datos.knob_capas(indice)].escrituras == 0
        for indice in range(1, datos.POOL + 1)
    )


def test_migrar_legacy_con_excedente_conserva_el_respaldo_y_lo_cuenta():
    """S8: el legacy que supera el pool queda intacto como respaldo."""
    nodo = _nodo_vacio()
    texto_legacy = json.dumps([{"frame": indice} for indice in range(datos.POOL + 3)])
    nodo[datos.KNOB_LEGACY].setValue(texto_legacy)

    assert datos.migrar_legacy(nodo) is True
    assert len(datos.leer_filas(nodo)) == datos.POOL
    assert nodo[datos.KNOB_LEGACY].value() == texto_legacy
    assert datos.legacy_excedente(nodo) == 3


def test_migrar_legacy_sin_excedente_limpia_el_respaldo():
    """S8: el legacy que cabe entero se elimina y no reporta excedente."""
    nodo = _nodo_vacio()
    nodo[datos.KNOB_LEGACY].setValue(json.dumps([{"frame": 10}]))

    assert datos.migrar_legacy(nodo) is True
    assert nodo[datos.KNOB_LEGACY].value() == ""
    assert datos.legacy_excedente(nodo) == 0
