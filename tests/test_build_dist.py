"""Comportamiento verificable del generador de la distribución mínima."""

import ast
from pathlib import Path

import pytest

from SamanTools import build_dist, componentes


def _por_id(identificador):
    return next(item for item in componentes.COMPONENTES if item["id"] == identificador)


def test_cierre_de_fspy_incluye_limpiar_transitivamente():
    cierre, procedencia = build_dist.resolver_cierre(componentes.COMPONENTES)
    assert "SamanTools/limpiar.py" in cierre
    assert "SamanTools/registro.py" in procedencia["SamanTools/limpiar.py"]


def test_build_falla_si_falta_archivo_declarado(tmp_path):
    declaracion = dict(_por_id("fspy"))
    declaracion["assets"] = ["SamanTools/nodos/no-existe.gizmo"]

    with pytest.raises(build_dist.ErrorDeBuild, match="archivo declarado no existe"):
        build_dist.construir(tmp_path / "dist", componentes=[declaracion])


def test_build_falla_si_un_componente_activo_necesita_modulo_excluido(tmp_path):
    declaracion = dict(_por_id("fspy"))
    declaracion["modulos"] = list(declaracion["modulos"]) + ["SamanTools/panel_comentarios.py"]

    with pytest.raises(build_dist.ErrorDeBuild, match="módulo excluido"):
        build_dist.construir(tmp_path / "dist", componentes=[declaracion])


def test_build_falla_si_un_componente_verificado_no_tiene_tests(tmp_path):
    declaracion = dict(_por_id("fspy"))
    declaracion["tests"] = ()

    with pytest.raises(build_dist.ErrorDeBuild, match="verificado.*tests asociados"):
        build_dist.construir(tmp_path / "dist", componentes=[declaracion])


def test_manifiesto_lista_cada_componente_y_su_estado(tmp_path):
    resultado = build_dist.construir(tmp_path / "dist")
    manifiesto = (Path(resultado["destino"]) / "MANIFIESTO.md").read_text(encoding="utf-8")

    for componente in componentes.COMPONENTES:
        assert componente["id"] in manifiesto
        assert ("verificado" if componente["activo"] else "excluido") in manifiesto

    actualizacion = manifiesto.split("## actualizacion", 1)[1].split("## ", 1)[0]
    assert "bootstrap/menu.py" in actualizacion
    assert "tests/test_bootstrap_menu.py" in actualizacion
    assert "Cantidad de tests: 3" in actualizacion
    assert (Path(resultado["destino"]) / "bootstrap" / "menu.py").is_file()


def test_dist_no_importa_modulos_internos_fuera_de_si_mismo(tmp_path):
    destino = Path(build_dist.construir(tmp_path / "dist")["destino"])
    paquete = destino / "SamanTools"
    incluidos = {archivo.relative_to(destino).as_posix() for archivo in paquete.rglob("*.py")}

    for archivo in paquete.rglob("*.py"):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"), filename=str(archivo))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                nombres = [alias.name for alias in nodo.names]
            elif isinstance(nodo, ast.ImportFrom) and nodo.module:
                nombres = [nodo.module]
            else:
                continue
            for nombre in nombres:
                if nombre.startswith("SamanTools."):
                    esperado = nombre.replace(".", "/") + ".py"
                    assert esperado in incluidos, "%s importa %s fuera del dist" % (archivo, nombre)
