"""
Tests de SamanTools.rutas: lógica del nodo Rutas.

El caso clave: actualizar() debe decidir si un Read con ruta dinámica
[python ...] cambió de valor y solo entonces ejecutar reload.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nuke
from SamanTools import rutas


def _nodo_rutas(usuario="MacServer"):
    """Crea un nodo falso tipo Rutas con los knobs que actualizar() usa."""
    n = nuke.NodoFake(cls="NoOp", nombre="Rutas1")
    n.knobs_d["UsuarioActivo"] = nuke.KnobFake(usuario)
    n.knobs_d["TO_VFX_SERVER_MAC"] = nuke.KnobFake("/vol/TO_VFX")
    n.knobs_d["comp_SERVER_MAC"] = nuke.KnobFake("/vol/COMP")
    n.knobs_d["FROM_VFX_SERVER_MAC"] = nuke.KnobFake("/vol/FROM_VFX")
    n.knobs_d["RutaActual"] = nuke.KnobFake("")
    return n


def _read_dinamico(script, resuelto="RESUELTA_DINAMICA"):
    r = nuke.NodoFake()
    k = nuke.KnobFake(resuelto)
    k.script = script
    r.knobs_d["file"] = k
    r.knobs_d["reload"] = nuke.KnobFake("")
    r.knobs_d["reload"].ejecutado = 0
    k._read = r
    # sobreescribimos execute() de reload con contador
    class ReloadFake(nuke.KnobFake):
        def execute(self):
            self.ejecutado += 1
    r.knobs_d["reload"] = ReloadFake("")
    r.knobs_d["reload"].ejecutado = 0
    return r


class TestActualizar:
    def _setup(self, nodos):
        nuke._estado["nodos"] = nodos
        nuke._estado["nodo_actual"] = nodos[0]
        nuke._estado["mensajes"] = []

    def test_usuario_valido_actualiza_variables(self):
        n = _nodo_rutas()
        self._setup([n])
        import __main__
        antes = getattr(__main__, "PYTHON_TO_VFX", None)
        rutas.actualizar(n)
        assert getattr(__main__, "PYTHON_TO_VFX", None) == "/vol/TO_VFX"
        assert getattr(__main__, "PYTHON_COMP", None) == "/vol/COMP"
        assert getattr(__main__, "PYTHON_FROM_VFX", None) == "/vol/FROM_VFX"

    def test_reload_solo_para_read_que_cambio(self):
        cambiante = _read_dinamico("[python {x}]", resuelto="ANTES")
        estable = _read_dinamico("[python {y}]", resuelto="IGUAL")
        n = _nodo_rutas()
        self._setup([n, cambiante, estable])

        # Simular que fromScript re-evalua: cambiante pasa de ANTES a DESPUES,
        # estable queda en IGUAL.
        def re_evaluar():
            cambiante["file"].valor = "DESPUES"
            estable["file"].valor = "IGUAL"

        # Reemplazamos fromScript por la simulacion (lo que hace Nuke real)
        def fromScript_fake(self, s):
            self.script = s
            re_evaluar()
        cambiante["file"].__class__.fromScript = fromScript_fake
        estable["file"].__class__.fromScript = fromScript_fake

        rutas.actualizar(n)

        assert cambiante["reload"].ejecutado == 1   # cambió -> reload
        assert estable["reload"].ejecutado == 0     # no cambió -> sin reload

    def test_actualiza_etiqueta_ruta(self):
        n = _nodo_rutas()
        self._setup([n])
        rutas.actualizar(n)
        etiqueta = n["RutaActual"].value()
        assert "TO_VFX: /vol/TO_VFX" in etiqueta
        assert "COMP: /vol/COMP" in etiqueta
        assert "FROM_VFX: /vol/FROM_VFX" in etiqueta

    def test_usuario_invalido_no_hace_nada(self):
        n = _nodo_rutas(usuario="Inexistente")
        self._setup([n])
        import __main__
        antes = getattr(__main__, "PYTHON_COMP", "SIN_CAMBIAR")
        rutas.actualizar(n)
        assert getattr(__main__, "PYTHON_COMP", "SIN_CAMBIAR") == antes

    def test_sin_nodo_devuelve_false(self):
        nuke._estado["nodo_actual"] = None
        assert rutas.actualizar(None) is False


class TestAplicarProyecto:
    def test_aplicar_proyecto_escribe_variables_sin_recargar(self):
        n = _nodo_rutas()
        r = _read_dinamico("[python {x}]")
        nuke._estado["nodos"] = [n, r]
        import __main__
        rutas.aplicar_proyecto(n)
        assert getattr(__main__, "PYTHON_TO_VFX", None) == "/vol/TO_VFX"
        assert getattr(__main__, "PYTHON_COMP", None) == "/vol/COMP"
        assert getattr(__main__, "PYTHON_FROM_VFX", None) == "/vol/FROM_VFX"
        assert r["reload"].ejecutado == 0


class TestRefrescarFuentes:
    def test_refrescar_fuentes_sin_forzar_solo_cambia_lo_que_cambio(self):
        cambiante = _read_dinamico("[python {x}]", resuelto="ANTES")
        estable = _read_dinamico("[python {y}]", resuelto="IGUAL")
        n = _nodo_rutas()
        nuke._estado["nodos"] = [n, cambiante, estable]

        # Simular que fromScript re-evalua: cambiante pasa de ANTES a DESPUES,
        # estable queda en IGUAL (mismo patron que test_reload_solo_para_read...).
        def re_evaluar():
            cambiante["file"].valor = "DESPUES"
            estable["file"].valor = "IGUAL"

        def fromScript_fake(self, s):
            self.script = s
            re_evaluar()

        cambiante["file"].__class__.fromScript = fromScript_fake
        estable["file"].__class__.fromScript = fromScript_fake

        assert rutas.refrescar_fuentes(n) == 1
        assert cambiante["reload"].ejecutado == 1
        assert estable["reload"].ejecutado == 0

    def test_refrescar_fuentes_forzar_recarga_todos(self):
        r1 = _read_dinamico("[python {x}]", resuelto="IGUAL")
        r2 = _read_dinamico("[python {y}]", resuelto="IGUAL")
        n = _nodo_rutas()
        nuke._estado["nodos"] = [n, r1, r2]

        assert rutas.refrescar_fuentes(n, forzar=True) == 2
        assert r1["reload"].ejecutado == 1
        assert r2["reload"].ejecutado == 1


class TestCambiarProyecto:
    def _nodo_con_rutas(self):
        n = nuke.NodoFake(cls="NoOp", nombre="Rutas2")
        n.knobs_d["UsuarioActivo"] = nuke.KnobFake("MacServer")
        n.knobs_d["TO_VFX_SERVER_MAC"] = nuke.KnobFake("/Volumes/wupm/2026/HTLR/TO_VFX/")
        n.knobs_d["comp_SERVER_MAC"] = nuke.KnobFake("/Volumes/wupm/2026/HTLR/COMP/")
        n.knobs_d["FROM_VFX_SERVER_MAC"] = nuke.KnobFake("/Volumes/wupm/2026/HTLR/FROM_VFX/")
        return n

    def test_cambiar_proyecto_en_rutas_reescribe_segmento(self):
        n = self._nodo_con_rutas()
        assert rutas._cambiar_proyecto_en_rutas(n, "PCF") == 3
        assert n["TO_VFX_SERVER_MAC"].value() == "/Volumes/wupm/2026/PCF/TO_VFX/"
        assert n["comp_SERVER_MAC"].value() == "/Volumes/wupm/2026/PCF/COMP/"
        assert n["FROM_VFX_SERVER_MAC"].value() == "/Volumes/wupm/2026/PCF/FROM_VFX/"
        assert rutas._cambiar_proyecto_en_rutas(n, "PCF") == 0

    def test_cambiar_proyecto_valida_proyecto_vacio(self, monkeypatch):
        n = self._nodo_con_rutas()
        n.knobs_d["string"] = nuke.KnobFake("")
        mensajes = []
        monkeypatch.setattr(nuke, "message", lambda m: mensajes.append(m))
        rutas.cambiar_proyecto(n)
        assert len(mensajes) == 1
        assert "ingrese un código" in mensajes[0]
        assert n["TO_VFX_SERVER_MAC"].value() == "/Volumes/wupm/2026/HTLR/TO_VFX/"

    def test_cambiar_proyecto_avisa_cantidad(self, monkeypatch):
        n = self._nodo_con_rutas()
        n.knobs_d["string"] = nuke.KnobFake("PCF")
        r = _read_dinamico("[python {x}]")
        nuke._estado["nodos"] = [n, r]
        mensajes = []
        monkeypatch.setattr(nuke, "message", lambda m: mensajes.append(m))
        import __main__
        rutas.cambiar_proyecto(n)
        assert any("Se actualizaron 3 rutas" in m for m in mensajes)
        assert r["reload"].ejecutado == 0
        assert (
            getattr(__main__, "PYTHON_TO_VFX", None)
            == "/Volumes/wupm/2026/PCF/TO_VFX/"
        )


class TestRefrescarFuentesBoton:
    def test_refrescar_fuentes_boton_mensajes(self, monkeypatch):
        n = _nodo_rutas()
        r = _read_dinamico("[python {x}]")
        nuke._estado["nodos"] = [n, r]
        mensajes = []
        monkeypatch.setattr(nuke, "message", lambda m: mensajes.append(m))
        rutas.refrescar_fuentes_boton(n)
        assert any("Se recargaron 1" in m for m in mensajes)

        nuke._estado["nodos"] = [n]
        mensajes[:] = []
        rutas.refrescar_fuentes_boton(n)
        assert any("No se encontraron" in m for m in mensajes)