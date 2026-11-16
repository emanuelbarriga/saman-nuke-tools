"""Genera una distribución autocontenida desde :mod:`SamanTools.componentes`.

No importa Nuke: puede ejecutarse con el Python del sistema para inspeccionar
la clausura de imports y preparar el artefacto antes de abrir Nuke.
"""

import argparse
import ast
import datetime
import os
from pathlib import Path
import shutil
import subprocess

from .componentes import COMPONENTES, EXCLUIDOS


RAIZ_REPOSITORIO = Path(__file__).resolve().parent.parent


class ErrorDeBuild(RuntimeError):
    """Un manifiesto o una dependencia impide crear un dist verificable."""


def _normalizar(ruta):
    return Path(ruta).as_posix()


def _es_excluido(ruta, excluidos=EXCLUIDOS):
    ruta = _normalizar(ruta)
    return any(ruta == clave or ruta.startswith(clave) for clave in excluidos)


def _ruta_modulo(nombre):
    return "SamanTools/" + nombre.replace(".", "/") + ".py"


def _imports_internos(ruta, raiz=RAIZ_REPOSITORIO):
    """Devuelve los imports de SamanTools, incluso los definidos en funciones."""
    ruta = Path(ruta)
    arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))
    resultado = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                if alias.name == "SamanTools":
                    resultado.add("SamanTools/__init__.py")
                elif alias.name.startswith("SamanTools."):
                    resultado.add(_ruta_modulo(alias.name[len("SamanTools."):]))
        elif isinstance(nodo, ast.ImportFrom):
            if nodo.level:
                relativo = ruta.parent
                for _ in range(nodo.level - 1):
                    relativo = relativo.parent
                prefijo = relativo.relative_to(raiz).as_posix().replace("/", ".")
                modulo = (prefijo + "." + nodo.module) if nodo.module else prefijo
            else:
                modulo = nodo.module or ""
            if modulo == "SamanTools":
                for alias in nodo.names:
                    if alias.name == "__version__":
                        resultado.add("SamanTools/__init__.py")
                    elif alias.name != "*":
                        resultado.add(_ruta_modulo(alias.name))
            elif modulo.startswith("SamanTools."):
                resultado.add(_ruta_modulo(modulo[len("SamanTools."):]))
    return resultado


def resolver_cierre(componentes, raiz=RAIZ_REPOSITORIO, excluidos=EXCLUIDOS):
    """Calcula la clausura AST y su procedencia para componentes activos."""
    raiz = Path(raiz)
    pendientes = []
    procedencia = {}
    cierre = set()
    for componente in componentes:
        if not componente.get("activo", True):
            continue
        for ruta in componente.get("modulos", ()):
            ruta = _normalizar(ruta)
            if _es_excluido(ruta, excluidos):
                raise ErrorDeBuild("componente activo necesita módulo excluido: %s" % ruta)
            if ruta.startswith("SamanTools/"):
                pendientes.append((ruta, "componente %s" % componente["id"]))
    while pendientes:
        relativo, padre = pendientes.pop()
        if relativo in cierre:
            continue
        absoluto = raiz / relativo
        if not absoluto.is_file():
            raise ErrorDeBuild("import interno resuelve fuera de SamanTools/dist: %s (desde %s)" % (relativo, padre))
        if _es_excluido(relativo, excluidos):
            raise ErrorDeBuild("componente activo necesita módulo excluido: %s (desde %s)" % (relativo, padre))
        cierre.add(relativo)
        procedencia.setdefault(relativo, padre)
        for dependencia in _imports_internos(absoluto, raiz):
            if _es_excluido(dependencia, excluidos):
                raise ErrorDeBuild("componente activo necesita módulo excluido: %s (desde %s)" % (dependencia, relativo))
            pendientes.append((dependencia, relativo))
    return cierre, procedencia


def _validar_declaraciones(componentes, raiz):
    for componente in componentes:
        if componente.get("activo", True) and not componente.get("tests", ()):
            raise ErrorDeBuild(
                "componente verificado sin tests asociados: %s" % componente["id"]
            )
        for ruta in tuple(componente.get("modulos", ())) + tuple(componente.get("assets", ())) + tuple(componente.get("tests", ())):
            if not (raiz / ruta).is_file():
                raise ErrorDeBuild("archivo declarado no existe: %s (componente %s)" % (ruta, componente["id"]))


def _cantidad_tests(rutas, raiz):
    cantidad = 0
    for ruta in rutas:
        arbol = ast.parse((raiz / ruta).read_text(encoding="utf-8"), filename=ruta)
        cantidad += sum(isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and nodo.name.startswith("test_") for nodo in ast.walk(arbol))
    return cantidad


def _commit_origen(raiz):
    try:
        return subprocess.check_output(["git", "-C", str(raiz), "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "desconocido"


def _manifiesto(componentes, cierre, raiz):
    lineas = [
        "# Manifiesto de SamanTools",
        "",
        "- Fecha: %s" % datetime.datetime.now(datetime.UTC).isoformat(),
        "- Commit de origen: %s" % _commit_origen(raiz),
        "",
    ]
    for componente in componentes:
        estado = "verificado" if componente.get("activo", True) else "excluido"
        lineas += [
            "## %s — %s" % (componente["id"], componente["etiqueta"]),
            "",
            "- Estado: %s" % estado,
            "- Módulos: %s" % ", ".join(componente.get("modulos", ())),
            "- Nodos/assets: %s" % ", ".join(componente.get("assets", ())),
            "- Tests asociados: %s" % ", ".join(componente.get("tests", ())),
            "- Cantidad de tests: %d" % _cantidad_tests(componente.get("tests", ()), raiz),
            "",
        ]
    lineas += ["## Cierre de dependencias", ""]
    lineas += ["- %s" % ruta for ruta in sorted(cierre)]
    return "\n".join(lineas) + "\n"


def construir(destino=None, componentes=None, raiz=RAIZ_REPOSITORIO):
    """Construye *destino* y devuelve sus rutas y la clausura calculada.

    Los archivos declarados se sobrescriben para que ``dist/samantools`` se
    pueda regenerar con un único comando.
    """
    raiz = Path(raiz)
    destino = Path(destino) if destino is not None else raiz / "dist" / "samantools"
    componentes = tuple(COMPONENTES if componentes is None else componentes)
    _validar_declaraciones(componentes, raiz)
    cierre, procedencia = resolver_cierre(componentes, raiz)
    destino.mkdir(parents=True, exist_ok=True)
    for relativo in sorted(cierre | {"SamanTools/componentes.py"}):
        origen = raiz / relativo
        if not origen.is_file():
            raise ErrorDeBuild("archivo declarado no existe: %s" % relativo)
        salida = destino / relativo
        salida.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origen, salida)
    for componente in componentes:
        if not componente.get("activo", True):
            continue
        for relativo in componente.get("assets", ()):
            salida = destino / relativo
            salida.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(raiz / relativo, salida)
        for relativo in componente.get("modulos", ()):
            if not relativo.startswith("SamanTools/"):
                salida = destino / relativo
                salida.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(raiz / relativo, salida)
                # Compatibilidad con la ubicación de instalación del artista:
                # bootstrap/menu.py termina copiado como ~/.nuke/menu.py.
                if relativo == "bootstrap/menu.py":
                    shutil.copy2(raiz / relativo, destino / "menu.py")
    (destino / "MANIFIESTO.md").write_text(_manifiesto(componentes, cierre, raiz), encoding="utf-8")
    return {"destino": str(destino), "modulos": sorted(cierre), "procedencia": procedencia}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Genera dist/samantools desde el manifiesto único.")
    parser.add_argument("--destino", default=None, help="Directorio de salida vacío (por defecto dist/samantools).")
    args = parser.parse_args(argv)
    resultado = construir(args.destino)
    print("Distribución generada en %s (%d módulos)." % (resultado["destino"], len(resultado["modulos"])))


if __name__ == "__main__":
    main()
