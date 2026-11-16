"""Contrato de seguridad del bootstrap que se instala en ``~/.nuke/menu.py``."""

import ast
from pathlib import Path
import py_compile


BOOTSTRAP = Path(__file__).resolve().parent.parent / "bootstrap" / "menu.py"


def _funcion(nombre):
    arbol = ast.parse(BOOTSTRAP.read_text(encoding="utf-8"), filename=str(BOOTSTRAP))
    return next(nodo for nodo in ast.walk(arbol) if isinstance(nodo, ast.FunctionDef) and nodo.name == nombre)


def _fuente(nodo):
    lineas = BOOTSTRAP.read_text(encoding="utf-8").splitlines()
    return "\n".join(lineas[nodo.lineno - 1:nodo.end_lineno])


def test_bootstrap_compila_y_conserva_entradas_de_mantenimiento(tmp_path):
    py_compile.compile(str(BOOTSTRAP), cfile=str(tmp_path / "menu.pyc"), doraise=True)
    assert _funcion("_actualizar_ahora")
    assert _funcion("_desinstalar_ahora")


def test_auto_update_es_fast_forward_y_no_hace_reset_duro():
    fuente = _fuente(_funcion("_auto_actualizar"))
    assert '"pull", "--ff-only", "--quiet"' in fuente
    assert "reset --hard" not in fuente
    assert '"pull"' not in fuente.replace('"pull", "--ff-only", "--quiet"', "")


def test_bootstrap_se_auto_sincroniza_por_hash():
    fuente = _fuente(_funcion("_auto_actualizar_bootstrap"))
    assert "hashlib.md5" in fuente
    assert "shutil.copy2(repo_boot, local)" in fuente
