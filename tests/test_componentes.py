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


def test_los_cinco_nodos_llevan_los_creditos_del_estudio():
    """S2/S13: cada nodo publicado muestra los créditos del estudio.

    Solo `Breakdown` los tenía. Sin este test, un asset rehecho los pierde otra
    vez y nadie lo nota hasta que un artista abre el nodo.
    """
    nodos = (
        "SamanTools/nodos/Rutas.gizmo",
        "SamanTools/nodos/Breakdown.gizmo",
        "SamanTools/nodos/Review.gizmo",
        "SamanTools/nodos/ColorSpaces.gizmo",
        "SamanTools/nodos/fSpy.gizmo",
    )
    for ruta in nodos:
        with open(ruta, encoding="utf-8") as archivo:
            contenido = archivo.read()
        assert "Créditos" in contenido, "sin créditos: %s" % ruta
        assert "emanuel.barriga@samanestudio.com" in contenido, "sin contacto: %s" % ruta
