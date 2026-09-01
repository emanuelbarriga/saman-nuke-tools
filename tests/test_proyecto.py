"""
Tests de SamanTools.proyecto: carga dinámica de herramientas por proyecto.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nuke
from SamanTools import proyecto


class TestClasificar:
    def test_galeria_por_palabra_asset(self):
        assert proyecto._clasificar("electrical_sparks_vol_1") == "Galerías"

    def test_galeria_blood(self):
        assert proyecto._clasificar("blood_splat") == "Galerías"

    def test_herramienta_breakdown(self):
        assert proyecto._clasificar("Breakdown") == "Herramientas"

    def test_herramienta_review(self):
        assert proyecto._clasificar("Review") == "Herramientas"

    def test_muzzlehtlr_no_es_galeria(self):
        # 'muzzle' solo califica cuando es galería (muzzle_flashes_*),
        # no la herramienta MuzzleHTLR.
        assert proyecto._clasificar("MuzzleHTLR") == "Herramientas"

    def test_muzzle_flashes_si_es_galeria(self):
        assert proyecto._clasificar("muzzle_flashes_vol2") == "Galerías"


class TestEscanear:
    def _crear_scripts(self, tmp_path, archivos):
        for rel in archivos:
            ruta = tmp_path / rel
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.touch()
        return str(tmp_path)

    def test_escaneo_raiz(self, tmp_path):
        ruta = self._crear_scripts(tmp_path, ["Breakdown.gizmo", "Review.gizmo"])
        res = proyecto._escanear(ruta)
        assert ("Breakdown", "Breakdown") in res
        assert ("Review", "Review") in res

    def test_escaneo_recursivo_con_etiqueta(self, tmp_path):
        ruta = self._crear_scripts(tmp_path, ["Galerias/sparks_vol1.gizmo"])
        res = proyecto._escanear(ruta)
        assert ("sparks_vol1", "Galerias/sparks_vol1") in res

    def test_ignora_no_gizmo(self, tmp_path):
        ruta = self._crear_scripts(tmp_path, ["nota.txt", "img.png"])
        assert proyecto._escanear(ruta) == []


class TestObtenerRutaScripts:
    def test_sin_comp_devuelve_none(self, monkeypatch, tmp_path):
        # Sin PYTHON_COMP ni variable de entorno
        monkeypatch.delenv("PYTHON_COMP", raising=False)
        import __main__
        monkeypatch.delattr(__main__, "PYTHON_COMP", raising=False)
        assert proyecto.obtener_ruta_scripts() is None

    def test_comp_sin_carpeta_scripts(self, monkeypatch, tmp_path):
        import __main__
        monkeypatch.setattr(__main__, "PYTHON_COMP", str(tmp_path))
        assert proyecto.obtener_ruta_scripts() is None

    def test_comp_con_carpeta_scripts(self, monkeypatch, tmp_path):
        import __main__
        comp = tmp_path
        (comp / "Scripts").mkdir()
        monkeypatch.setattr(__main__, "PYTHON_COMP", str(comp))
        assert proyecto.obtener_ruta_scripts() == str(comp / "Scripts")

    def test_comp_desde_env_var(self, monkeypatch, tmp_path):
        comp = tmp_path
        (comp / "Scripts").mkdir()
        import sys as _sys
        main_fake = _sys.modules["__main__"]
        monkeypatch.delattr(main_fake, "PYTHON_COMP", raising=False)
        monkeypatch.setenv("PYTHON_COMP", str(comp))
        assert proyecto.obtener_ruta_scripts() == str(comp / "Scripts")


def _nodo_rutas_con_proyecto(proyecto_valor):
    """NodoFake con knobs 'UsuarioActivo', 'RutaActual' y 'string'."""
    nodo = nuke.NodoFake(cls="Rutas", nombre="Rutas1")
    nodo.knobs_d["UsuarioActivo"] = nuke.KnobFake("ARTIST")
    nodo.knobs_d["RutaActual"] = nuke.KnobFake("ruta")
    nodo.knobs_d["string"] = nuke.KnobFake(proyecto_valor)
    return nodo


class TestGetComp:
    def test_desde_main(self, monkeypatch):
        import __main__
        monkeypatch.setattr(__main__, "PYTHON_COMP", "/ruta/comp")
        monkeypatch.setenv("PYTHON_COMP", "/ruta/env")
        assert proyecto._get_comp() == "/ruta/comp"

    def test_vacio_cae_a_env(self, monkeypatch):
        import __main__
        monkeypatch.setattr(__main__, "PYTHON_COMP", "")
        monkeypatch.setenv("PYTHON_COMP", "/ruta/env")
        assert proyecto._get_comp() == "/ruta/env"


class TestNombreProyecto:
    def test_con_nodo_lee_knob_string(self):
        nuke._estado["nodos"] = [_nodo_rutas_con_proyecto("  HTLR  ")]
        try:
            assert proyecto._nombre_proyecto() == "HTLR"
        finally:
            nuke._estado["nodos"] = []

    def test_sin_nodos_proyecto_por_defecto(self):
        nuke._estado["nodos"] = []
        assert proyecto._nombre_proyecto() == "Proyecto"


class TestActualizarDesdeNodoRutas:
    def test_delega_en_rutas_actualizar(self, monkeypatch):
        from SamanTools import rutas

        llamadas = []

        def _espia(nodo):
            llamadas.append(nodo)
            return True

        monkeypatch.setattr(rutas, "actualizar", _espia)
        nodo = _nodo_rutas_con_proyecto("HTLR")
        assert proyecto.actualizar_desde_nodo_rutas(nodo) is True
        assert llamadas == [nodo]


class TestCargarScriptsProyecto:
    def _reset_menu(self):
        menu = nuke.menu("Nodes")
        menu._items[:] = []
        menu.commands[:] = []
        menu.removed[:] = []

    def _submenu_de(self, menu, nombre):
        return next(
            (sub for sub in menu._items if getattr(sub, "_nombre", None) == nombre),
            None,
        )

    def _ruta_scripts(self, monkeypatch, tmp_path, archivos):
        scripts = tmp_path / "Scripts"
        scripts.mkdir(exist_ok=True)
        for nombre in archivos:
            (scripts / nombre).touch()
        import __main__
        monkeypatch.setattr(__main__, "PYTHON_COMP", str(tmp_path))
        return str(scripts)

    def test_carga_scripts_y_agrupa_por_categoria(self, monkeypatch, tmp_path):
        self._reset_menu()
        ruta_scripts = self._ruta_scripts(
            monkeypatch, tmp_path, ["mis_refs.gizmo", "muzzle_flashes_v1.gizmo"]
        )

        assert proyecto.cargar_scripts_proyecto() is True
        assert ruta_scripts in nuke._estado["plugins"]

        menu = nuke.menu("Nodes")
        submenu = self._submenu_de(menu, proyecto.SUBMENU)
        assert submenu is not None, "Falta el submenu del proyecto"

        herramientas = self._submenu_de(submenu, "Herramientas")
        galerias = self._submenu_de(submenu, "Galerías")
        assert herramientas is not None
        assert galerias is not None
        assert [name for (name, _) in herramientas.commands] == ["mis_refs"]
        assert [name for (name, _) in galerias.commands] == ["muzzle_flashes_v1"]

    def test_sin_ruta_devuelve_false_y_limpia_submenu(self, monkeypatch):
        self._reset_menu()
        import __main__
        monkeypatch.setattr(__main__, "PYTHON_COMP", "")

        assert proyecto.cargar_scripts_proyecto() is False
        menu = nuke.menu("Nodes")
        assert self._submenu_de(menu, proyecto.SUBMENU) is None

    def test_ruta_existente_sin_gizmos_devuelve_false(self, monkeypatch, tmp_path):
        self._reset_menu()
        self._ruta_scripts(monkeypatch, tmp_path, ["nota.txt", "img.png"])

        assert proyecto.cargar_scripts_proyecto() is False
        menu = nuke.menu("Nodes")
        assert self._submenu_de(menu, proyecto.SUBMENU) is None