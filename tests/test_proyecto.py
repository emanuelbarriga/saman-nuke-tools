"""
Tests de SamanTools.proyecto: carga dinámica de herramientas por proyecto.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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