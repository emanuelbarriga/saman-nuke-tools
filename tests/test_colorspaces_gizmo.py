"""Contrato estructural del nodo ColorSpaces (S2).

El nodo es autocontenido: su motor vive en el knob `Cerebro_Python` y no importa
nada de SamanTools. Estos tests fijan ese contrato, los botones de su panel y el
despachador de acciones, sin necesitar Nuke.
"""

import os

RUTA = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "SamanTools",
    "nodos",
    "ColorSpaces.gizmo",
)


def _contenido():
    with open(RUTA, encoding="utf-8") as archivo:
        return archivo.read()


def test_es_un_gizmo_valido():
    contenido = _contenido()
    assert "NoOp {" in contenido
    assert "name ColorSpaces" in contenido
    assert contenido.rstrip().endswith("}")


def test_lleva_su_motor_embebido():
    contenido = _contenido()
    assert "addUserKnob {52 Cerebro_Python " in contenido
    assert "colorspaces_engine" in contenido


def test_no_depende_de_los_modulos_de_samantools():
    contenido = _contenido()
    assert "import SamanTools" not in contenido
    assert "from SamanTools" not in contenido
    assert "sys.path" not in contenido


def test_declara_los_botones_de_su_panel():
    contenido = _contenido()
    for accion in ("clasificar", "limpiar", "buscar", "aplicar", "recargar"):
        assert "btn_%s" % accion in contenido
        assert "'_CS_ACCION': '%s'" % accion in contenido


def test_el_motor_despacha_todas_sus_acciones():
    # El motor viaja serializado dentro de un string de Tcl: las comillas van
    # escapadas. Se normaliza antes de buscar el mapa de acciones.
    contenido = _contenido().replace('\\"', '"')
    for accion in ("clasificar", "limpiar", "aplicar", "buscar", "recargar", "init"):
        assert '"%s": "_%s"' % (accion, accion) in contenido
