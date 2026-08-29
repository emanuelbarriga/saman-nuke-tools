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