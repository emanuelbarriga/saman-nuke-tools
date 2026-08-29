"""
Tests de SamanTools.nombres: parseo de nombres de platos/planos VFX.

'parsear_plato' es puro (sin nuke) y testeable con pytest. Los casos cubren
el canonico, los nombres malformados del cliente (version en el medio), las
refs PNG sin version, rutas Windows con backslashes y entradas invalidas.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from SamanTools import entorno
from SamanTools import nombres


# --------------------------------------------------------------------------
# Canonico y malformados
# --------------------------------------------------------------------------


def test_plato_canonico():
    res = nombres.parsear_plato(
        "/Volumes/wupm/2026/HTLR/TO_VFX/EP_107/20260826/"
        "HTLR_107_008_00100_V01.mov"
    )
    assert res["proyecto"] == "HTLR"
    assert res["capitulo"] == 107
    assert res["escena"] == "008"
    assert res["shot"] == "00100"
    assert res["plano"] == "008_00100"
    assert res["version"] == "V01"
    assert res["malformado"] is False
    assert res["canonico"] == res["archivo"] == "HTLR_107_008_00100_V01.mov"


def test_plato_malformado_version_en_el_medio():
    res = nombres.parsear_plato(
        "/Volumes/wupm/2026/HTLR/TO_VFX/EP_108/20260819/"
        "HTLR_108_012_V01_0100.mov"
    )
    assert res["proyecto"] == "HTLR"
    assert res["capitulo"] == 108
    assert res["escena"] == "012"
    assert res["shot"] == "0100"
    assert res["plano"] == "012_0100"
    assert res["version"] == "V01"
    assert res["malformado"] is True
    assert res["canonico"] == "HTLR_108_012_0100_V01.mov"


def test_plato_malformado_segundo_ejemplo():
    res = nombres.parsear_plato(
        "/Volumes/wupm/2026/HTLR/TO_VFX/EP_108/20260819/"
        "HTLR_108_034_V01_0100.mov"
    )
    assert res["malformado"] is True
    assert res["canonico"] == "HTLR_108_034_0100_V01.mov"


# --------------------------------------------------------------------------
# Version / refs PNG / basename suelto
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "archivo,esperado",
    [
        ("HTLR_107_008_00100_v01.mov", "HTLR_107_008_00100_V01.mov"),
        ("HTLR_107_008_00100_V01.mov", "HTLR_107_008_00100_V01.mov"),
    ],
)
def test_version_se_normaliza_a_mayuscula(archivo, esperado):
    res = nombres.parsear_plato(archivo)
    assert res["version"] == "V01"
    assert res["canonico"] == esperado


def test_png_sin_version():
    res = nombres.parsear_plato("HTLR_107_012_01500.png")
    assert res["proyecto"] is None
    assert res["version"] is None
    assert res["malformado"] is False
    assert res["canonico"] == "HTLR_107_012_01500.png"
    assert res["plano"] == "012_01500"


def test_solo_basename_reconoce_contenido():
    res = nombres.parsear_plato("HTLR_109_020_00300_V02.mov")
    assert res["proyecto"] is None
    assert res["capitulo"] == 109
    assert res["plano"] == "020_00300"
    assert res["version"] == "V02"


# --------------------------------------------------------------------------
# Ruta Windows con backslashes
# --------------------------------------------------------------------------


def test_ruta_windows_backslashes():
    ruta = r"L:\2026\HTLR\TO_VFX\EP_110\20260901\HTLR_110_055_01200_V03.mov"
    esperado = entorno.proyecto_desde_ruta(ruta)
    # En la maquina de test (macOS) la base L:/2026 no esta montada, asi que
    # 'proyecto' sale None; en Windows/Linux con la unidad montada sale
    # 'HTLR'. Asumimos el valor real de la funcion y solo fijamos el resto.
    res = nombres.parsear_plato(ruta)
    assert res["proyecto"] == esperado
    assert res["capitulo"] == 110
    assert res["escena"] == "055"
    assert res["shot"] == "01200"
    assert res["plano"] == "055_01200"
    assert res["malformado"] is False
    assert res["canonico"] == "HTLR_110_055_01200_V03.mov"


# --------------------------------------------------------------------------
# Entradas invalidas
# --------------------------------------------------------------------------


@pytest.mark.parametrize("entrada", ["", None, "foo.txt"])
def test_entradas_invalidas_devuelven_none(entrada):
    assert nombres.parsear_plato(entrada) is None


def test_capitulo_de_ruta_es_autoritativo():
    # El filename dice '999' pero la ruta dice EP_107: manda la carpeta. El
    # filename queda inconsistente, pero el capitulo autoritativo es el de
    # la carpeta y el canonico se reconstruye coherente con ese valor.
    ruta = (
        "/Volumes/wupm/2026/HTLR/TO_VFX/EP_107/20260826/"
        "HTLR_999_008_00100_V01.mov"
    )
    res = nombres.parsear_plato(ruta)
    assert res["capitulo"] == 107
    assert res["canonico"] == "HTLR_107_008_00100_V01.mov"


def test_comp_nk_con_sufijo_empresa_no_contamina_plano():
    # La convencion real es {PROYECTO}_{EP}_{escena}_{shot}_comp_SAMAN_V{nn}.nk
    # con 'comp_SAMAN' como sufijo de EMPRESA (no artista). El sufijo es
    # metadato: no entra al plano, pero se conserva en el canonico.
    res = nombres.parsear_plato("HTLR_100_000_00000_comp_SAMAN_V01.nk")
    assert isinstance(res, dict)
    assert res["capitulo"] == 100
    assert res["escena"] == "000"
    assert res["shot"] == "00000"
    assert res["plano"] == "000_00000"
    assert res["version"] == "V01"
    assert res["malformado"] is False
    assert res["canonico"] == "HTLR_100_000_00000_comp_SAMAN_V01.nk"


def test_comp_nk_con_otro_nombre_empresa():
    # Cualquier token tras 'comp' es metadato de empresa: no contamina el plano.
    res = nombres.parsear_plato("HTLR_107_008_00100_comp_OTRA_V02.nk")
    assert res["plano"] == "008_00100"
    assert res["canonico"] == "HTLR_107_008_00100_comp_OTRA_V02.nk"