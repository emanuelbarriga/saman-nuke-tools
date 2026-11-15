"""
Tests del modelo de columnas configurables del nodo Breakdown.

Cubren qué columnas declara el nodo, cómo se guardan los valores de cada tipo
(tilde en la máscara, texto y número en `TXT`) y las cuatro ramas de migración
a `datos_ver = 2`. Corren fuera de Nuke: el nodo falso sólo necesita
`knobs()`, `knob.value()` y `knob.setValue()`.
"""

import json

import pytest

from SamanTools import breakdown_datos as datos


class KnobFalso(object):
    def __init__(self, valor=0):
        self._valor = valor
        self.escrituras = 0

    def value(self):
        return self._valor

    def setValue(self, valor):
        self._valor = valor
        self.escrituras += 1


class NodoFalso(object):
    def __init__(self, **knobs):
        self._knobs = {n: KnobFalso(v) for n, v in knobs.items()}

    def knobs(self):
        return self._knobs

    def __getitem__(self, nombre):
        return self._knobs[nombre]

    def escrituras(self):
        return {n for n, k in self._knobs.items() if k.escrituras}


def _nodo(columnas=2, textos="", **over):
    """Nodo con el contrato completo del .gizmo v2."""
    knobs = {
        datos.KNOB_FILAS: 0,
        datos.KNOB_LEGACY: "",
        datos.KNOB_VERSION: datos.VERSION_DATOS,
        datos.KNOB_TEXTOS: textos,
        datos.KNOB_COLUMNAS: columnas,
    }
    for i in range(1, datos.POOL + 1):
        knobs[datos.knob_frame(i)] = 0
        knobs[datos.knob_capas(i)] = 0
    for i in range(1, datos.MAX_COLUMNAS + 1):
        knobs[datos.knob_col_nombre(i)] = datos.COLUMNAS_EJEMPLO[i - 1]["nombre"] if i <= 2 else ""
        knobs[datos.knob_col_tipo(i)] = (
            datos.COLUMNAS_EJEMPLO[i - 1]["tipo"].capitalize() if i <= 2 else "Tilde"
        )
    knobs.update(over)
    return NodoFalso(**knobs)


# ------------------------------------------------------- modelo de columnas


def test_constantes_del_modelo():
    assert datos.TIPOS == ("tilde", "texto", "numero")
    assert datos.MAX_COLUMNAS == 8
    assert datos.MASCARA_COLUMNAS == 255


def test_columnas_canonicas_son_las_cinco_capas_en_tilde():
    assert datos.COLUMNAS_CANONICAS == [
        {"nombre": "Brillo", "tipo": "tilde"},
        {"nombre": "Muzzle", "tipo": "tilde"},
        {"nombre": "Humo", "tipo": "tilde"},
        {"nombre": "Impacto", "tipo": "tilde"},
        {"nombre": "Sangre", "tipo": "tilde"},
    ]


def test_columnas_de_ejemplo_muestran_tilde_y_texto():
    assert datos.COLUMNAS_EJEMPLO == [
        {"nombre": "Muzzle", "tipo": "tilde"},
        {"nombre": "Nota", "tipo": "texto"},
    ]


def test_normalizar_etiquetas_de_tipo_del_knob():
    cols = datos.normalizar_columnas(
        [
            {"nombre": "A", "tipo": "Tilde"},
            {"nombre": "B", "tipo": "Texto"},
            {"nombre": "C", "tipo": "Numero"},
            {"nombre": "D", "tipo": "desconocido"},
        ]
    )
    # Las columnas no declaradas se completan en tilde para poder iterar slots.
    assert [c["tipo"] for c in cols] == ["tilde", "texto", "numero", "tilde"] + ["tilde"] * 4


def test_normalizar_pone_nombre_por_defecto_y_recorta_al_maximo():
    cols = datos.normalizar_columnas([{"nombre": "", "tipo": "tilde"}] * 20)
    assert len(cols) == datos.MAX_COLUMNAS
    assert cols[0]["nombre"] == "Columna 1"
    assert cols[7]["nombre"] == "Columna 8"


def test_leer_columnas_respeta_la_cantidad():
    nodo = _nodo(columnas=2)
    assert datos.leer_columnas(nodo) == datos.COLUMNAS_EJEMPLO


def test_leer_columnas_con_cantidad_cero_es_solo_frame():
    assert datos.leer_columnas(_nodo(columnas=0)) == []


def test_escribir_columnas_escribe_cantidad_y_slots_y_limpia_sobrantes():
    nodo = _nodo(columnas=5)
    datos.escribir_columnas(nodo, datos.COLUMNAS_EJEMPLO)

    assert nodo[datos.KNOB_COLUMNAS].value() == 2
    assert datos.leer_columnas(nodo) == datos.COLUMNAS_EJEMPLO


def test_escribir_columnas_no_escribe_si_no_cambia():
    nodo = _nodo(columnas=2)
    datos.escribir_columnas(nodo, datos.COLUMNAS_EJEMPLO)
    assert nodo.escrituras() == set()


def test_bit_de_columna_es_slot_menos_uno():
    assert datos.bit_de_columna(1) == 1
    assert datos.bit_de_columna(2) == 2
    assert datos.bit_de_columna(8) == 128


# ------------------------------------------------------------ valores


def test_valor_de_celda_tilde_sale_de_la_mascara():
    nodo = _nodo(columnas=2)
    datos.escribir_filas(nodo, [{"frame": 10, "capas": 1}, {"frame": 20, "capas": 0}])
    textos = datos.leer_textos(nodo)

    assert datos.valor_celda({"frame": 10, "capas": 1}, textos, 1, 1, "tilde") is True
    assert datos.valor_celda({"frame": 20, "capas": 0}, textos, 2, 1, "tilde") is False


def test_valor_de_celda_texto_y_numero_salen_de_txt():
    nodo = _nodo(textos=json.dumps({"1": {"2": "humo leve", "3": "4"}}))
    textos = datos.leer_textos(nodo)
    fila = {"frame": 10, "capas": 0}

    assert datos.valor_celda(fila, textos, 1, 2, "texto") == "humo leve"
    assert datos.valor_celda(fila, textos, 1, 3, "numero") == "4"
    assert datos.valor_celda(fila, textos, 2, 2, "texto") == ""


def test_textos_corruptos_o_vacios_no_rompen():
    assert datos.leer_textos(_nodo(textos="")) == {}
    assert datos.leer_textos(_nodo(textos="{no es json")) == {}
    assert datos.leer_textos(_nodo(textos="[1,2]")) == {}


def test_escribir_textos_normaliza_a_enteros_y_omite_vacios():
    nodo = _nodo()
    datos.escribir_textos(nodo, {"1": {"2": "hola"}, "3": {"2": ""}})

    assert json.loads(nodo[datos.KNOB_TEXTOS].value()) == {"1": {"2": "hola"}}
    assert datos.leer_textos(nodo) == {1: {2: "hola"}}


def test_escribir_textos_no_escribe_si_no_cambia():
    nodo = _nodo(textos=json.dumps({"1": {"2": "hola"}}))
    datos.escribir_textos(nodo, {1: {2: "hola"}})
    assert nodo.escrituras() == set()


def test_escribir_celda_tilde_escribe_solo_su_mascara():
    nodo = _nodo(columnas=2)
    datos.escribir_filas(
        nodo,
        [
            {"frame": 10, "capas": 0},
            {"frame": 20, "capas": 0},
            {"frame": 30, "capas": 0},
        ],
    )
    for knob in nodo.knobs().values():
        knob.escrituras = 0

    datos.escribir_celda(nodo, 2, 2, True)

    assert nodo.escrituras() == {datos.knob_capas(2)}
    assert nodo[datos.knob_capas(2)].value() == 2


def test_escribir_celda_texto_escribe_solo_txt():
    nodo = _nodo(columnas=2)
    for knob in nodo.knobs().values():
        knob.escrituras = 0

    datos.escribir_celda(nodo, 3, 2, "nota")

    assert nodo.escrituras() == {datos.KNOB_TEXTOS}
    assert datos.leer_textos(nodo) == {3: {2: "nota"}}


def test_escribir_celda_apagar_tilde_conserva_el_resto_de_la_fila():
    nodo = _nodo(columnas=2)
    datos.escribir_filas(nodo, [{"frame": 10, "capas": 3}])

    datos.escribir_celda(nodo, 1, 1, False)

    assert nodo[datos.knob_capas(1)].value() == 2


def test_cambiar_el_tipo_no_borra_los_valores():
    """S16: los valores quedan ocultos y reaparecen al volver al tipo."""
    nodo = _nodo(columnas=2)
    datos.escribir_filas(nodo, [{"frame": 10, "capas": 1}])
    datos.escribir_textos(nodo, {1: {1: "nota vieja"}})

    # La columna 1 pasa a texto: el tilde queda oculto, no borrado.
    datos.escribir_columnas(nodo, [{"nombre": "A", "tipo": "texto"}])
    assert nodo[datos.knob_capas(1)].value() == 1
    assert datos.valor_celda({"frame": 10, "capas": 1}, datos.leer_textos(nodo), 1, 1, "texto") == "nota vieja"

    # Vuelve a tilde: el tilde y el texto siguen ahí.
    datos.escribir_columnas(nodo, [{"nombre": "A", "tipo": "tilde"}])
    assert datos.valor_celda({"frame": 10, "capas": 1}, datos.leer_textos(nodo), 1, 1, "tilde") is True
    assert datos.leer_textos(nodo) == {1: {1: "nota vieja"}}


# ---------------------------------------------------------- migracion v2


def _legacy(filas):
    return json.dumps([{"frame": f, "brillo": b, "muzzle": m, "humo": h, "impacto": i, "sangre": s}
                       for f, b, m, h, i, s in filas])


def test_nodo_nuevo_no_migra_filas_y_conserva_las_columnas_de_ejemplo():
    nodo = _nodo(columnas=2, **{datos.KNOB_VERSION: 0, datos.KNOB_FILAS: 3,
                                "F_1": 10, "F_2": 20, "F_3": 30})

    assert datos.migrar_legacy(nodo) is False
    assert datos.leer_filas(nodo) == [
        {"frame": 10, "capas": 0},
        {"frame": 20, "capas": 0},
        {"frame": 30, "capas": 0},
    ]
    assert datos.leer_columnas(nodo) == datos.COLUMNAS_EJEMPLO
    assert nodo[datos.KNOB_VERSION].value() == datos.VERSION_DATOS


def test_comp_del_gizmo_original_pasa_a_cinco_columnas_canonicas():
    nodo = _nodo(columnas=2, **{datos.KNOB_VERSION: 0,
                                datos.KNOB_LEGACY: _legacy([(10, True, False, False, False, False)])})

    assert datos.migrar_legacy(nodo) is True
    assert datos.leer_columnas(nodo) == datos.COLUMNAS_CANONICAS
    assert datos.leer_filas(nodo) == [{"frame": 10, "capas": 1}]
    assert nodo[datos.KNOB_LEGACY].value() == ""


def test_comp_viejo_con_tabla_vacia_queda_sin_filas_fantasma():
    nodo = _nodo(columnas=2, **{datos.KNOB_VERSION: 0, datos.KNOB_LEGACY: "[]",
                                datos.KNOB_FILAS: 3, "F_1": 10, "F_2": 20, "F_3": 30})

    datos.migrar_legacy(nodo)

    assert datos.leer_filas(nodo) == []
    assert datos.leer_columnas(nodo) == datos.COLUMNAS_CANONICAS


def test_comp_de_la_v1_pasa_a_cinco_columnas_sin_tocar_filas():
    nodo = _nodo(columnas=2, **{datos.KNOB_VERSION: 1, datos.KNOB_FILAS: 1, "F_1": 15, "L_1": 8})

    assert datos.migrar_legacy(nodo) is True
    assert datos.leer_columnas(nodo) == datos.COLUMNAS_CANONICAS
    assert datos.leer_filas(nodo) == [{"frame": 15, "capas": 8}]


def test_comp_v2_no_se_toca():
    nodo = _nodo(columnas=2, **{datos.KNOB_VERSION: 2})
    assert datos.migrar_legacy(nodo) is False
    assert nodo.escrituras() == set()


def test_migracion_con_excedente_conserva_el_respaldo_y_las_columnas():
    filas = [(i * 10, True, False, False, False, False) for i in range(1, 41)]
    texto = _legacy(filas)
    nodo = _nodo(columnas=2, **{datos.KNOB_VERSION: 0, datos.KNOB_LEGACY: texto})

    assert datos.migrar_legacy(nodo) is True
    assert len(datos.leer_filas(nodo)) == datos.POOL
    assert nodo[datos.KNOB_LEGACY].value() == texto
    assert datos.legacy_excedente(nodo) == 8
    assert datos.leer_columnas(nodo) == datos.COLUMNAS_CANONICAS
