"""
Tests de la gestion del nodo unico Rutas (maximo 1 por proyecto).

Cubre: es_nodo_rutas/es_version_actual, encontrar_nodos_rutas,
ruta_nk_por_defecto, crear_o_reutilizar (0/1/1-viejo/varios nodos) y
_reconstruir_nodo (migracion de valores + posicion).

Se usa el stub de nuke del conftest; nuke.delete/Undo/EndUndo y el
comportamiento de nodePaste se monkeypatchen aqui (tolerantes en el stub).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import nuke
from SamanTools import entorno
from SamanTools import proyecto
from SamanTools import rutas


def _nodo_rutas(usuario="MacServer", version="nueva", nombre="Rutas1"):
    """Nodo falso tipo Rutas con los knobs caracteristicos."""
    n = nuke.NodoFake(cls="NoOp", nombre=nombre)
    n.knobs_d["UsuarioActivo"] = nuke.KnobFake(usuario)
    n.knobs_d["string"] = nuke.KnobFake("HTLR")
    n.knobs_d["RutaActual"] = nuke.KnobFake("")
    for suf in ("MAC", "WINDOWS", "ARTIST"):
        n.knobs_d["TO_VFX_SERVER_" + suf] = nuke.KnobFake("/vol/TO")
        n.knobs_d["comp_SERVER_" + suf] = nuke.KnobFake("/vol/COMP")
        n.knobs_d["FROM_VFX_SERVER_" + suf] = nuke.KnobFake("/vol/FROM")
    if version == "nueva":
        n.knobs_d["SeccionEntorno"] = nuke.KnobFake("")
        n.knobs_d["SO_Detectado"] = nuke.KnobFake("")
        n.knobs_d["EstadoUnidad"] = nuke.KnobFake("")
        n.knobs_d["UsuarioRecomendado"] = nuke.KnobFake("")
    return n


@pytest.fixture(autouse=True)
def _limpiar_estado():
    """Escena limpia antes y despues de cada test."""
    nuke._estado["nodos"] = []
    nuke._estado["nodo_actual"] = None
    nuke._estado["seleccionados"] = []
    nuke._estado["mensajes"] = []
    rutas._refrescando = False
    yield
    rutas._refrescando = False
    nuke._estado["nodos"] = []
    nuke._estado["nodo_actual"] = None
    nuke._estado["mensajes"] = []


def _ambiente_estable(monkeypatch):
    """Evita subprocess reales y re-escaneo de proyecto en actualizar()."""
    monkeypatch.setattr(entorno, "primera_ruta_disponible", lambda so, extra=None: None)
    monkeypatch.setattr(proyecto, "cargar_scripts_proyecto", lambda: False)


def _contador_paste(monkeypatch):
    contador = {"veces": 0}

    def fake_paste(ruta):
        contador["veces"] += 1
        return _nodo_rutas()

    monkeypatch.setattr(nuke, "nodePaste", fake_paste)
    return contador


# --------------------------------------------------------------------------
# Identificacion del nodo
# --------------------------------------------------------------------------


def test_es_nodo_rutas_identifica_por_knobs_no_por_nombre():
    assert rutas.es_nodo_rutas(_nodo_rutas()) is True
    assert rutas.es_nodo_rutas(_nodo_rutas(nombre="MiNodoRenombrado")) is True
    assert rutas.es_nodo_rutas(nuke.NodoFake()) is False
    assert rutas.es_nodo_rutas(None) is False


def test_actualizar_no_rompe_sin_knob_ruta_actual(monkeypatch):
    _ambiente_estable(monkeypatch)
    n = _nodo_rutas()
    n.knobs_d.pop("RutaActual", None)  # version actual: sin la etiqueta vieja
    nuke._estado["nodos"] = [n]
    nuke._estado["nodo_actual"] = n
    import __main__
    rutas.actualizar(n)
    assert getattr(__main__, "PYTHON_TO_VFX", None) == "/vol/TO"
    assert getattr(__main__, "PYTHON_COMP", None) == "/vol/COMP"


def test_es_nodo_rutas_detecta_estructura_nueva_sin_ruta_actual():
    n = _nodo_rutas()
    n.knobs_d.pop("RutaActual", None)  # la version actual ya no tiene RutaActual
    assert rutas.es_nodo_rutas(n) is True


def test_es_nodo_rutas_no_falso_positivo_con_solo_usuario_activo():
    n = nuke.NodoFake()
    n.knobs_d["UsuarioActivo"] = nuke.KnobFake("MacServer")
    assert rutas.es_nodo_rutas(n) is False


def test_es_version_actual_positivo_y_negativo():
    assert rutas.es_version_actual(_nodo_rutas(version="nueva")) is True
    assert rutas.es_version_actual(_nodo_rutas(version="vieja")) is False
    assert rutas.es_version_actual(nuke.NodoFake()) is False
    assert rutas.es_version_actual(None) is False


def test_encontrar_nodos_rutas_filtra_no_rutas():
    r1 = _nodo_rutas(nombre="Rutas1")
    r2 = _nodo_rutas(nombre="RutasRenombrado")
    read = nuke.NodoFake()
    nuke._estado["nodos"] = [r1, read, r2]
    assert rutas.encontrar_nodos_rutas() == [r1, r2]


def test_ruta_nk_por_defecto_apunta_a_archivo_existente():
    r = rutas.ruta_nk_por_defecto()
    assert os.path.basename(r) == "Rutas.nk"
    assert os.path.isabs(r)
    assert os.path.exists(r)


# --------------------------------------------------------------------------
# crear_o_reutilizar
# --------------------------------------------------------------------------


def test_crear_sin_nodos_pega_una_vez_y_devuelve_nodo(monkeypatch):
    _ambiente_estable(monkeypatch)
    contador = _contador_paste(monkeypatch)
    resultado = rutas.crear_o_reutilizar(ruta_nk="nodos/Rutas.nk")
    assert contador["veces"] == 1
    assert resultado is not None
    assert rutas.es_nodo_rutas(resultado)


def test_crear_con_nodo_actual_no_pega_y_enfoca_al_nodo(monkeypatch):
    n = _nodo_rutas()
    nuke._estado["nodos"] = [n]
    contador = _contador_paste(monkeypatch)

    llamadas = {"panel": 0, "zoom": 0}
    n.showControlPanel = lambda: llamadas.__setitem__("panel", llamadas["panel"] + 1)

    def fake_zoom():
        llamadas["zoom"] += 1

    monkeypatch.setattr(nuke, "zoomToFitSelected", fake_zoom, raising=False)

    resultado = rutas.crear_o_reutilizar()
    assert contador["veces"] == 0
    assert nuke._estado["mensajes"] == []  # sin aviso: la accion conduce al nodo
    assert resultado is n
    assert n.selected is True
    assert llamadas["panel"] == 1  # abrio las propiedades del nodo
    assert llamadas["zoom"] == 1   # centró el Node Graph en el nodo


def test_crear_con_nodo_viejo_acepta_reconstruir(monkeypatch):
    viejo = _nodo_rutas(usuario="Windows", version="vieja")
    viejo.knobs_d["string"] = nuke.KnobFake("PCF")
    viejo.knobs_d["TO_VFX_SERVER_MAC"] = nuke.KnobFake("/mi/TO")
    viejo.setXYpos(100, 200)
    nuke._estado["nodos"] = [viejo]
    _ambiente_estable(monkeypatch)

    nuevo = _nodo_rutas(version="nueva")
    contador = {"veces": 0}

    def fake_paste(ruta):
        contador["veces"] += 1
        return nuevo

    monkeypatch.setattr(nuke, "nodePaste", fake_paste, raising=False)
    monkeypatch.setattr(nuke, "delete", lambda x: None, raising=False)
    monkeypatch.setattr(nuke, "Undo", lambda: None, raising=False)
    monkeypatch.setattr(nuke, "EndUndo", lambda: None, raising=False)
    monkeypatch.setattr(nuke, "ask", lambda m: True, raising=False)

    resultado = rutas.crear_o_reutilizar(ruta_nk="nodos/Rutas.nk")
    assert contador["veces"] == 1
    assert resultado is nuevo
    assert nuevo["string"].value() == "PCF"
    assert nuevo["UsuarioActivo"].value() == "Windows"
    assert nuevo["TO_VFX_SERVER_MAC"].value() == "/mi/TO"
    assert nuevo.posxy == (100, 200)


def test_crear_con_nodo_viejo_niega_no_pega(monkeypatch):
    viejo = _nodo_rutas(version="vieja")
    nuke._estado["nodos"] = [viejo]
    contador = _contador_paste(monkeypatch)
    monkeypatch.setattr(nuke, "ask", lambda m: False)
    resultado = rutas.crear_o_reutilizar()
    assert contador["veces"] == 0
    assert any("version anterior" in m for m in nuke._estado["mensajes"])
    assert resultado is viejo


def test_crear_con_duplicados_avisa_cantidad_sin_pegar(monkeypatch):
    a = _nodo_rutas(nombre="Rutas1")
    b = _nodo_rutas(nombre="Rutas2")
    nuke._estado["nodos"] = [a, b]
    contador = _contador_paste(monkeypatch)
    resultado = rutas.crear_o_reutilizar()
    assert contador["veces"] == 0
    assert any("2 nodos Rutas" in m for m in nuke._estado["mensajes"])
    assert resultado is a


# --------------------------------------------------------------------------
# _reconstruir_nodo
# --------------------------------------------------------------------------


def test_reconstruir_nodo_copia_valores_y_posicion(monkeypatch):
    viejo = _nodo_rutas(usuario="Artist", version="vieja")
    viejo.knobs_d["string"] = nuke.KnobFake("ZXY")
    viejo.knobs_d["FROM_VFX_SERVER_ARTIST"] = nuke.KnobFake("/art/FROM")
    viejo.setXYpos(-50, 300)
    _ambiente_estable(monkeypatch)

    nuevo = _nodo_rutas(version="nueva")
    llamadas_undo = {"abrio": 0, "cerro": 0}

    def fake_undo():
        llamadas_undo["abrio"] += 1

    def fake_endundo():
        llamadas_undo["cerro"] += 1

    monkeypatch.setattr(nuke, "delete", lambda x: None, raising=False)
    monkeypatch.setattr(nuke, "Undo", fake_undo, raising=False)
    monkeypatch.setattr(nuke, "EndUndo", fake_endundo, raising=False)
    monkeypatch.setattr(nuke, "nodePaste", lambda ruta: nuevo, raising=False)

    resultado = rutas._reconstruir_nodo(viejo, "nodos/Rutas.nk")
    assert resultado is nuevo
    assert llamadas_undo == {"abrio": 1, "cerro": 1}
    assert nuevo["string"].value() == "ZXY"
    assert nuevo["UsuarioActivo"].value() == "Artist"
    assert nuevo["FROM_VFX_SERVER_ARTIST"].value() == "/art/FROM"
    assert nuevo.posxy == (-50, 300)


def test_reconstruir_nodo_sin_undo_no_rompe(monkeypatch):
    viejo = _nodo_rutas(version="vieja")
    nuevo = _nodo_rutas(version="nueva")
    # nuke.Undo/EndUndo/delete NO existen en este escenario (nivel stub).
    monkeypatch.setattr(nuke, "nodePaste", lambda ruta: nuevo, raising=False)
    _ambiente_estable(monkeypatch)
    resultado = rutas._reconstruir_nodo(viejo, "nodos/Rutas.nk")
    assert resultado is nuevo
    assert nuevo["string"].value() == "HTLR"


# --------------------------------------------------------------------------
# avisar_duplicados
# --------------------------------------------------------------------------


def test_avisar_duplicados_avisa_con_varios_nodos():
    a = _nodo_rutas(nombre="Rutas1")
    b = _nodo_rutas(nombre="Rutas2")
    nuke._estado["nodos"] = [a, b]
    rutas.avisar_duplicados(a)
    assert any("2 nodos Rutas" in m for m in nuke._estado["mensajes"])


def test_avisar_duplicados_silencioso_con_un_nodo():
    nuke._estado["nodos"] = [_nodo_rutas()]
    rutas.avisar_duplicados()
    assert nuke._estado["mensajes"] == []


def test_avisar_duplicados_ignora_nodo_que_no_es_rutas():
    a = _nodo_rutas(nombre="Rutas1")
    b = _nodo_rutas(nombre="Rutas2")
    read = nuke.NodoFake()
    nuke._estado["nodos"] = [a, b, read]
    rutas.avisar_duplicados(read)
    assert nuke._estado["mensajes"] == []