"""Tests de seleccion de version de comp: mtime real y flujo asistido del CLI.

Cubren:

- Seleccion por mtime real del SO (RC-SS-02): mtime gana pese a ``_V`` menor,
  tie-break ``_V012`` > ``_V005``, se ignoran ``.nk~``/``.autosave``/``.tmp``/
  puntos; ``analizar_version`` marca ``sospechosa`` y ``--use-version`` la
  resuelve.
- Abort sin ``.nk`` calificante nombrando la carpeta (RC-SS-02/03).
- Flags del CLI (RC-SS-03): ``--proyecto`` (default HTLR con aviso),
  ``--comp-dir``, ``--resolve-latest`` y confirmacion
  [Confirmar] / [Ver lista y desmarcar]; legacy sin flags nuevos no se toca.

Sin Nuke: usa tmp_path + os.utime sobre archivos reales y la confirmacion con
input inyectado. Las bases son ficticias (raices de ejemplo del spec,
permitidas en tests).
"""

import argparse
import os
import time
from pathlib import Path

import pytest

from render_distribuido import layouts
from render_distribuido import render_distribuido as orquestador

HTLR = layouts.LAYOUTS["HTLR"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def config_con_proyectos(tmp_path, habilitados=None):
    """Config ficticia: base local = tmp_path, proyectos habilitados."""
    if habilitados is None:
        habilitados = {"HTLR": True, "IPYD": True, "PCF": True}
    return {
        "bases_por_so": {"macOS": str(tmp_path)},
        "proyectos": habilitados,
    }


def _so_macos(monkeypatch):
    """Fuerza el SO local del orquestador a macOS en el modulo layouts."""
    monkeypatch.setattr(layouts.platform, "system", lambda: "Darwin")


def tocar(archivo, mtime):
    """Escribe el archivo (si no existe) y fija su mtime real."""
    if not os.path.exists(archivo):
        Path(archivo).write_text("x", encoding="utf-8")
    os.utime(archivo, (mtime, mtime))


def carpeta_comp(tmp_path, nombre):
    """Crea la carpeta de un comp y devuelve su Path."""
    ruta = tmp_path / nombre
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def _args_cli(**opciones):
    """Namespace de args del orquestador con defaults del flujo asistido."""
    base = {
        "proyecto": None,
        "comp_dir": None,
        "resolve_latest": False,
        "use_version": None,
    }
    base.update(opciones)
    return argparse.Namespace(**base)


# RC-SS-02: seleccion por mtime real (orquestador), nunca por V-number
# ---------------------------------------------------------------------------


def test_mejor_version_mtime_gana_pese_a_v_menor(tmp_path):
    """v001 tocado hoy gana a v015 aprobado hace un mes (RC-SS-02)."""
    ahora = time.time()
    tocar(tmp_path / "plan_comp_SAMAN_v001.nk", ahora)
    tocar(tmp_path / "plan_comp_SAMAN_v015.nk", ahora - 30 * 86400)

    elegida = layouts.mejor_version_comp(str(tmp_path), HTLR)

    assert elegida == "plan_comp_SAMAN_v001.nk"


def test_mejor_version_empate_de_mtime_resuelve_por_v_mayor(tmp_path):
    """Mismo mtime: _V012 gana a _V005 (tie-break RC-SS-02)."""
    hora = 1700000000.0
    tocar(tmp_path / "plan_comp_SAMAN_v005.nk", hora)
    tocar(tmp_path / "plan_comp_SAMAN_v012.nk", hora)

    elegida = layouts.mejor_version_comp(str(tmp_path), HTLR)

    assert elegida == "plan_comp_SAMAN_v012.nk"


def test_candidatas_ignoran_autosave_y_temp(tmp_path):
    """Solo el .nk real califica: .nk~, .autosave, .tmp y puntos se ignoran."""
    tocar(tmp_path / "plan_comp_SAMAN_v003.nk~", time.time())
    tocar(tmp_path / "plan_comp_SAMAN_v003.nk.autosave", time.time())
    tocar(tmp_path / "plan_comp_SAMAN_v001.nk.tmp", time.time())
    tocar(tmp_path / ".plan_comp_SAMAN_v004.nk", time.time())
    tocar(tmp_path / "plan_comp_SAMAN_v002.nk", time.time())

    resumen = layouts.analizar_version(str(tmp_path), HTLR)

    assert resumen["candidatas"] == ["plan_comp_SAMAN_v002.nk"]
    assert resumen["elegida"] == "plan_comp_SAMAN_v002.nk"


def test_analizar_version_sospechosa_con_falso_positivo(tmp_path):
    """Elegida por mtime con _V menor a otra candidata => sospechosa True."""
    ahora = time.time()
    tocar(tmp_path / "plan_comp_SAMAN_v001.nk", ahora)
    tocar(tmp_path / "plan_comp_SAMAN_v015.nk", ahora - 30 * 86400)

    resumen = layouts.analizar_version(str(tmp_path), HTLR)

    assert resumen["elegida"] == "plan_comp_SAMAN_v001.nk"
    assert resumen["sospechosa"] is True
    assert sorted(resumen["candidatas"]) == [
        "plan_comp_SAMAN_v001.nk",
        "plan_comp_SAMAN_v015.nk",
    ]


def test_analizar_version_no_sospechosa_con_una_candidata(tmp_path):
    """Una sola version => nunca sospechosa."""
    tocar(tmp_path / "plan_comp_SAMAN_v007.nk", time.time())

    resumen = layouts.analizar_version(str(tmp_path), HTLR)

    assert resumen["elegida"] == "plan_comp_SAMAN_v007.nk"
    assert resumen["sospechosa"] is False


# ---------------------------------------------------------------------------
# RC-SS-02/03: abort sin .nk calificante + override de version
# ---------------------------------------------------------------------------


def test_sin_nk_aborta_nombrando_la_carpeta(tmp_path):
    """Carpeta vacia => SinCompError que nombra la carpeta (RC-SS-03)."""
    with pytest.raises(layouts.SinCompError) as exc:
        layouts.mejor_version_comp(str(tmp_path), HTLR)

    assert str(tmp_path) in str(exc.value)


def test_sin_nk_solo_ignorables_aborta_nombrando_la_carpeta(tmp_path):
    """Solo .nk~ en la carpeta => SinCompError nombrando la carpeta."""
    tocar(tmp_path / "plan_comp_SAMAN_v003.nk~", time.time())

    with pytest.raises(layouts.SinCompError) as exc:
        layouts.analizar_version(str(tmp_path), HTLR)

    assert str(tmp_path) in str(exc.value)


def test_use_version_override_elige_v_menor(tmp_path):
    """--use-version V015 resuelve el falso positivo (RC-SS-02 [Usar v015])."""
    ahora = time.time()
    tocar(tmp_path / "plan_comp_SAMAN_v001.nk", ahora)
    tocar(tmp_path / "plan_comp_SAMAN_v015.nk", ahora - 30 * 86400)

    elegida = layouts.elegir_por_version(str(tmp_path), "V015", HTLR)

    assert elegida == "plan_comp_SAMAN_v015.nk"


def test_use_version_ausente_aborta_nombrando_disponibles(tmp_path):
    """Version pedida inexistente => abort con versiones disponibles."""
    tocar(tmp_path / "plan_comp_SAMAN_v001.nk", time.time())
    tocar(tmp_path / "plan_comp_SAMAN_v015.nk", time.time())

    with pytest.raises(layouts.SinCompError) as exc:
        layouts.elegir_por_version(str(tmp_path), "V099", HTLR)

    mensaje = str(exc.value)
    assert str(tmp_path) in mensaje
    assert "V099" in mensaje
    assert "disponibles" in mensaje


# ---------------------------------------------------------------------------
# RC-SS-03: flags del CLI y confirmacion de seleccion (orquestador)
# ---------------------------------------------------------------------------


def _args_cli(**opciones):
    """Namespace de args del orquestador con defaults del flujo asistido."""
    base = {
        "proyecto": None,
        "comp_dir": None,
        "resolve_latest": False,
        "use_version": None,
    }
    base.update(opciones)
    return argparse.Namespace(**base)


def test_resolver_proyecto_default_htlr_con_aviso(capsys):
    """Sin --proyecto => HTLR con aviso explicito; con flag, sin aviso."""
    proyecto, aviso = orquestador.resolver_proyecto(None)
    assert (proyecto, aviso) == ("HTLR", True)
    assert "HTLR" in capsys.readouterr().out

    proyecto, aviso = orquestador.resolver_proyecto("PCF")
    assert (proyecto, aviso) == ("PCF", False)
    assert capsys.readouterr().out == ""


def test_es_flujo_asistido_legacy_sin_flags_nuevos():
    """Legacy --comp sin flags nuevos => False (RC-QC-04, sin gate)."""
    args = _args_cli()
    assert orquestador.es_flujo_asistido(args) is False


def test_es_flujo_asistido_con_cada_flag_nuevo():
    """Cualquier flag nuevo activa el flujo asistido."""
    assert orquestador.es_flujo_asistido(_args_cli(proyecto="PCF")) is True
    assert orquestador.es_flujo_asistido(_args_cli(comp_dir="COMP/EP_07")) is True
    assert orquestador.es_flujo_asistido(_args_cli(resolve_latest=True)) is True
    assert orquestador.es_flujo_asistido(_args_cli(use_version="V015")) is True


def test_planos_del_proyecto_comp_dir_directo(tmp_path, monkeypatch):
    """--comp-dir con carpeta existente: se usa tal cual (RC-SS-03 directo)."""
    _so_macos(monkeypatch)
    carpeta = tmp_path / "HTLR" / "COMP" / "EP_07" / "plan_alpha_comp_SAMAN_V001"
    carpeta.mkdir(parents=True)
    cfg = config_con_proyectos(tmp_path)

    planos = orquestador.planos_del_proyecto(
        _args_cli(comp_dir="HTLR/COMP/EP_07/plan_alpha_comp_SAMAN_V001"), cfg
    )

    assert planos == ["HTLR/COMP/EP_07/plan_alpha_comp_SAMAN_V001"]


def test_planos_del_proyecto_intent_remapeado(tmp_path, monkeypatch):
    """--comp-dir con intencion inexistente => remapeo al layout (RC-SS-01)."""
    _so_macos(monkeypatch)
    ep = carpeta_comp(tmp_path, "HTLR/COMP/EP_07")
    carpeta_comp(ep, "plan_alpha_comp_SAMAN_V001")
    cfg = config_con_proyectos(tmp_path)

    planos = orquestador.planos_del_proyecto(_args_cli(comp_dir="2VFX/Capitulo_7"), cfg)

    assert planos == ["HTLR/COMP/EP_07/plan_alpha_comp_SAMAN_V001"]


def test_planos_del_proyecto_sin_comp_dir_aborta():
    """Sin --comp-dir => abort claro pidiendo la carpeta o intencion."""
    with pytest.raises(SystemExit) as exc:
        orquestador.planos_del_proyecto(_args_cli(), {"bases_por_so": {}})
    assert "--comp-dir" in str(exc.value.code)


def test_confirmar_planos_default_confirma_todos():
    """Respuesta vacia (default) => todos los planos confirmados."""
    planos = ["p%02d" % i for i in range(46)]
    args = _args_cli()
    confirmados = orquestador.confirmar_planos(planos, args, leer=lambda _: "")
    assert confirmados == planos


def test_confirmar_planos_desmarcar_deja_subset(tmp_path):
    """[Ver lista y desmarcar] con indices => subset confirmado (RC-SS-03)."""
    planos = ["p%02d" % i for i in range(46)]
    respuestas = iter(["lista", "1,2,46"])
    args = _args_cli()
    confirmados = orquestador.confirmar_planos(
        planos, args, leer=lambda _: next(respuestas)
    )
    assert len(confirmados) == 43
    assert "p00" not in confirmados  # indice 1 desmarcado
    assert "p01" not in confirmados  # indice 2 desmarcado
    assert "p45" not in confirmados  # indice 46 desmarcado
    assert "p02" in confirmados and "p44" in confirmados


def test_confirmar_planos_resolve_latest_sin_prompt():
    """--resolve-latest confirma en silencio (nunca llama a input)."""
    planos = ["p%02d" % i for i in range(46)]
    args = _args_cli(resolve_latest=True)

    def leer_inesperado(_):
        raise AssertionError("--resolve-latest no debe preguntar")

    confirmados = orquestador.confirmar_planos(planos, args, leer=leer_inesperado)
    assert confirmados == planos


def test_confirmar_planos_eof_confirma_todos():
    """Sin TTY (EOFError) => confirma todos, sin colgarse."""
    planos = ["p%02d" % i for i in range(46)]
    args = _args_cli()

    def leer_eof(_):
        raise EOFError

    confirmados = orquestador.confirmar_planos(planos, args, leer=leer_eof)
    assert confirmados == planos


def test_seleccionar_version_mtime_gana(tmp_path):
    """Seleccion del orquestador: mtime real gana (RC-SS-02)."""
    ahora = time.time()
    tocar(tmp_path / "plan_comp_SAMAN_v001.nk", ahora)
    tocar(tmp_path / "plan_comp_SAMAN_v015.nk", ahora - 30 * 86400)

    version = orquestador.seleccionar_version(str(tmp_path), _args_cli(), HTLR)

    assert version == "plan_comp_SAMAN_v001.nk"


def test_seleccionar_version_use_version_override(tmp_path):
    """--use-version V015 fuerza la version vieja aprobada (RC-SS-02)."""
    ahora = time.time()
    tocar(tmp_path / "plan_comp_SAMAN_v001.nk", ahora)
    tocar(tmp_path / "plan_comp_SAMAN_v015.nk", ahora - 30 * 86400)

    version = orquestador.seleccionar_version(
        str(tmp_path), _args_cli(use_version="V015"), HTLR
    )

    assert version == "plan_comp_SAMAN_v015.nk"


def test_seleccionar_version_sin_nk_aborta_nombrando_carpeta(tmp_path):
    """Carpeta sin .nk calificante => abort nombrando la carpeta (RC-SS-03)."""
    with pytest.raises(layouts.SinCompError) as exc:
        orquestador.seleccionar_version(str(tmp_path), _args_cli(), HTLR)
    assert str(tmp_path) in str(exc.value)


def test_seleccionar_version_use_version_mal_formato_aborta(tmp_path):
    """--use-version sin formato V\\d+ => abort claro."""
    with pytest.raises(SystemExit) as exc:
        orquestador.seleccionar_version(
            str(tmp_path), _args_cli(use_version="abc"), HTLR
        )
    assert "V\\d+" in str(exc.value.code)