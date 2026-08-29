"""
Tests de SamanTools.panel_comentarios: apertura del panel docked.

El bug historico: abrir_panel usaba p.panels() y p.getPanel(), que NO existen
en nukescripts.panels de Nuke 17.1 (el dict interno es __panels, privado).
Este test inyecta un stub con el API REAL (registerWidgetAsPanel +
addToPane solamente) y verifica que abrir_panel funcione con el.

El widget PySide se requiere para importar el modulo; si no hay PySide en el
runner se salta (no se testea la UI, solo la logica de apertura).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import nuke


pytest.importorskip("PySide6")


class _PanelFake:
    """PythonPanel simulado: registra que se llamo addToPane."""

    def __init__(self, widget, name, panel_id):
        self.widget = widget
        self.name = name
        self.panel_id = panel_id
        self.acoplado = False

    def addToPane(self):
        self.acoplado = True
        return self


class _PanelsFake:
    """Modulo nukescripts.panels con SOLO el API real de Nuke 17.1.

    A proposito NO expone panels() ni getPanel(): si el codigo bajo prueba
    intentara usarlos, el test fallaria con AttributeError.
    """

    def __init__(self):
        self.registrados = []

    def registerWidgetAsPanel(self, widget, name, panel_id, create=False):
        self.registrados.append((widget, name, panel_id, create))
        return _PanelFake(widget, name, panel_id)


@pytest.fixture
def nukescripts_panels_fake(monkeypatch):
    import types

    modulo = types.ModuleType("nukescripts.panels")
    fake = _PanelsFake()
    modulo.panels = fake  # nombre del atributo de este stub interno
    # registra el API real como atributos del modulo
    modulo.registerWidgetAsPanel = fake.registerWidgetAsPanel
    data = types.ModuleType("nukescripts")
    data.panels = modulo
    monkeypatch.setitem(sys.modules, "nukescripts", data)
    monkeypatch.setitem(sys.modules, "nukescripts.panels", modulo)
    return fake


@pytest.fixture
def panel_reset():
    from SamanTools import panel_comentarios

    panel_comentarios._PANEL = None
    yield panel_comentarios


def test_abrir_panel_registra_y_acopla(nukescripts_panels_fake, panel_reset):
    panel_reset.abrir_panel()
    # registrado UNA vez con el string evaluable, no con la clase directa
    assert len(nukescripts_panels_fake.registrados) == 1
    widget, nombre, panel_id, create = nukescripts_panels_fake.registrados[0]
    assert isinstance(widget, str)
    assert "PanelComentarios" in widget
    assert nombre == "Comentarios por Plano — SamanTools"
    assert panel_id == "pe.saman.vfxflow.comentarios"
    assert create is True
    # el panel devuelto se acoplo
    assert panel_reset._PANEL is not None
    assert panel_reset._PANEL.acoplado is True


def test_abrir_panel_reutiliza_sin_re_registrar(
    nukescripts_panels_fake, panel_reset
):
    panel_reset.abrir_panel()
    panel_reset.abrir_panel()
    assert len(nukescripts_panels_fake.registrados) == 1  # solo la primera


def test_abrir_panel_sin_nukescripts_no_rompe(panel_reset, monkeypatch):
    monkeypatch.delitem(sys.modules, "nukescripts", raising=False)
    monkeypatch.delitem(sys.modules, "nukescripts.panels", raising=False)
    # en modo no-GUI no debe lanzar
    try:
        panel_reset.abrir_panel()
    except Exception as e:  # pragma: no cover - el contrato es no lanzar
        raise AssertionError("abrir_panel lanzo sin nukescripts: %r" % e)