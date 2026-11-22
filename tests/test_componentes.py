"""Contrato del manifiesto único de componentes distribuibles."""

from SamanTools.componentes import COMPONENTES


def test_manifiesto_declara_los_cinco_nodos_y_el_soporte_del_release():
    """S2/S5: cinco nodos, más soporte de menú, actualización y proyecto."""
    assert {componente["id"] for componente in COMPONENTES} == {
        "rutas",
        "breakdown",
        "review",
        "colorspaces",
        "fspy",
        "acerca_de",
        "actualizacion",
        "nodos_proyecto",
    }
    for componente in COMPONENTES:
        assert {"id", "etiqueta", "modulos", "assets", "tests", "activo"} <= set(componente)


def test_componente_fspy_declara_el_svg_como_asset():
    fspy = next(componente for componente in COMPONENTES if componente["id"] == "fspy")
    assert "SamanTools/fSpy.svg" in fspy["assets"]
