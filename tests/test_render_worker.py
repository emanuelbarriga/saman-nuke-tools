"""Tests de render_distribuido.render_worker: sufijos SOLO desde env (D6).

El worker corre dentro de Nuke real; bajo pytest se importa con el stub
nuke de conftest y MODE=render (el bloque module-level ejecuta scriptOpen/
execute contra el stub, sin efectos reales). La logica de sufijos se expone
como funcion pura `sufijos_desde_env(env)` y `setear_variables(base)` se
verifica contra el `__main__` falso de conftest.

Contrato (D6): TO_SUF/COMP_SUF/FROM_SUF se leen exclusivamente de las
variables de entorno. Variable ausente => sufijo vacio (base sin
subdirectorio). NUNCA rutas hardcodeadas de estudio (/HTLR/...).
"""

import importlib
import sys
from pathlib import Path

import nuke
import pytest

MODULO = "render_distribuido.render_worker"
RUTA_WORKER = Path(__file__).resolve().parent.parent / "render_distribuido" / "render_worker.py"
CLAVES_SUFIJOS = ("TO_SUF", "COMP_SUF", "FROM_SUF")


@pytest.fixture
def worker(monkeypatch):
    """Importa render_worker con env controlado y stub minimo para MODE=render.

    El import ejecuta el bloque module-level (rama render): se stubbea
    nuke.scriptOpen/nuke.execute y se fija BASE/MODE. Los sufijos se
    eliminan del env para que cada test decida su presencia.
    """
    monkeypatch.setattr(nuke, "scriptOpen", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(nuke, "execute", lambda *a, **k: None, raising=False)
    monkeypatch.setenv("BASE", "/Volumes/wupm/2026")
    monkeypatch.setenv("MODE", "render")
    for k in CLAVES_SUFIJOS:
        monkeypatch.delenv(k, raising=False)
    sys.modules.pop(MODULO, None)
    yield importlib.import_module(MODULO)
    sys.modules.pop(MODULO, None)


@pytest.fixture(autouse=True)
def _restaurar_main(worker):
    """Deja el almacen __main__ como lo definio conftest ("" tras el test)."""
    yield
    main = sys.modules["__main__"]
    main.PYTHON_TO_VFX = ""
    main.PYTHON_COMP = ""
    main.PYTHON_FROM_VFX = ""


# ---------------------------------------------------------------------------
# sufijos_desde_env: funcion pura sobre el mapping de env
# ---------------------------------------------------------------------------


def test_sufijos_presentes_se_mantienen(worker):
    """Con las tres variables presentes, devuelve exactamente esos valores."""
    sufs = worker.sufijos_desde_env(
        {"TO_SUF": "/TO/", "COMP_SUF": "/COMP/", "FROM_SUF": "/FROM_VFX/"}
    )
    assert sufs == {"TO_SUF": "/TO/", "COMP_SUF": "/COMP/", "FROM_SUF": "/FROM_VFX/"}


def test_sufijos_ausentes_devuelven_vacio(worker):
    """Sin ninguna variable, los tres sufijos son '' (base sin subdirectorio)."""
    sufs = worker.sufijos_desde_env({})
    assert sufs == {"TO_SUF": "", "COMP_SUF": "", "FROM_SUF": ""}


def test_sufijos_parciales_solo_rellenan_presentes(worker):
    """Presencia parcial: solo la variable dada toma valor, el resto queda ''."""
    sufs = worker.sufijos_desde_env({"TO_SUF": "/TO/"})
    assert sufs["TO_SUF"] == "/TO/"
    assert sufs["COMP_SUF"] == ""
    assert sufs["FROM_SUF"] == ""


def test_sufijos_ignoran_otras_claves(worker):
    """Claves ajenas (BASE, etc.) no contaminan el dict de sufijos."""
    sufs = worker.sufijos_desde_env({"BASE": "/x", "COMP_SUF": "/C/"})
    assert sufs == {"TO_SUF": "", "COMP_SUF": "/C/", "FROM_SUF": ""}


# ---------------------------------------------------------------------------
# setear_variables: el worker aplica esos sufijos sobre la base
# ---------------------------------------------------------------------------


def test_setear_variables_env_presente(worker, monkeypatch):
    """Env presente: PYTHON_TO_VFX/COMP/FROM_VFX = base + sufijo del env."""
    monkeypatch.setenv("TO_SUF", "/TO/")
    monkeypatch.setenv("COMP_SUF", "/COMP/")
    monkeypatch.setenv("FROM_SUF", "/FROM_VFX/")
    worker.setear_variables("/Volumes/wupm/2026")
    main = sys.modules["__main__"]
    assert main.PYTHON_TO_VFX == "/Volumes/wupm/2026/TO/"
    assert main.PYTHON_COMP == "/Volumes/wupm/2026/COMP/"
    assert main.PYTHON_FROM_VFX == "/Volumes/wupm/2026/FROM_VFX/"


def test_setear_variables_sin_env_usa_la_base_sin_sufijo(worker):
    """Env ausente: las tres quedan en la base pelada, sin /HTLR/ ni inventos."""
    worker.setear_variables("/Volumes/wupm/2026")
    main = sys.modules["__main__"]
    assert main.PYTHON_TO_VFX == "/Volumes/wupm/2026"
    assert main.PYTHON_COMP == "/Volumes/wupm/2026"
    assert main.PYTHON_FROM_VFX == "/Volumes/wupm/2026"


# ---------------------------------------------------------------------------
# Guard de fuente: sin fallbacks de estudio hardcodeados (spec: Suffix defaults)
# ---------------------------------------------------------------------------


def test_worker_sin_fallbacks_htlr_hardcodeados(worker):
    """El codigo del worker no contiene NINGUNA ruta /HTLR/ literal."""
    fuente = RUTA_WORKER.read_text(encoding="utf-8")
    assert "/HTLR/" not in fuente