"""Tests de render_distribuido.layouts: layout declarativo y resolucion de planos.

Cubren:

- Layouts declarativos por proyecto (RC-SS-01): raices relativas, remapeo de
  intenciones (``2VFX/Capitulo_7`` -> ``EP_07``, ``SC13`` -> ``PFC_SC13``,
  ``104`` -> IPYD), solo proyectos habilitados resuelven.
- RC-CN-05: los layouts son datos relativos (cero raices absolutas).
- ``localizar_plate`` con ``fecha_key`` (RC-QC-01): ``20260628-2`` >
  ``20260627``, override de fecha, abort sin carpeta de fecha.

Sin Nuke: usa tmp_path + os.utime sobre archivos reales. Las bases son
ficticias (raices de ejemplo del spec, permitidas en tests).
"""

import os
import time
from pathlib import Path

import pytest

from render_distribuido import layouts

HTLR = layouts.LAYOUTS["HTLR"]
IPYD = layouts.LAYOUTS["IPYD"]
PCF = layouts.LAYOUTS["PCF"]


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


# RC-SS-01: resolucion de planos por layout del proyecto
# ---------------------------------------------------------------------------


def test_resolver_planos_htlr_episodio(tmp_path, monkeypatch):
    """HTLR + 'Capitulo 7' => carpetas de planos bajo COMP/EP_07 (relativas)."""
    _so_macos(monkeypatch)
    ep = carpeta_comp(tmp_path, "HTLR/COMP/EP_07")
    carpeta_comp(ep, "plan_alpha_comp_SAMAN_V001")
    carpeta_comp(ep, "plan_beta_comp_SAMAN_V012")
    cfg = config_con_proyectos(tmp_path)

    planos = layouts.resolver_planos("Capitulo 7", "HTLR", cfg)

    assert planos == [
        "HTLR/COMP/EP_07/plan_alpha_comp_SAMAN_V001",
        "HTLR/COMP/EP_07/plan_beta_comp_SAMAN_V012",
    ]


def test_resolver_planos_remapea_intent_inexistente(tmp_path, monkeypatch):
    """'2VFX/Capitulo_7' no existe literal: se remapea a EP_07 (RC-SS-01)."""
    _so_macos(monkeypatch)
    ep = carpeta_comp(tmp_path, "HTLR/COMP/EP_07")
    carpeta_comp(ep, "plan_alpha_comp_SAMAN_V001")
    carpeta_comp(ep, "plan_beta_comp_SAMAN_V012")
    cfg = config_con_proyectos(tmp_path)

    planos = layouts.resolver_planos("2VFX/Capitulo_7", "HTLR", cfg)

    assert planos == [
        "HTLR/COMP/EP_07/plan_alpha_comp_SAMAN_V001",
        "HTLR/COMP/EP_07/plan_beta_comp_SAMAN_V012",
    ]


def test_resolver_planos_pcf_secuencia(tmp_path, monkeypatch):
    """PCF + 'SC13' => carpetas bajo COMP/PFC_SC13 (relativas)."""
    _so_macos(monkeypatch)
    ep = carpeta_comp(tmp_path, "PCF/COMP/PFC_SC13")
    carpeta_comp(ep, "plan_gamma_comp_SAMAN_V03")
    cfg = config_con_proyectos(tmp_path)

    planos = layouts.resolver_planos("SC13", "PCF", cfg)

    assert planos == ["PCF/COMP/PFC_SC13/plan_gamma_comp_SAMAN_V03"]


def test_resolver_planos_ipyd_episodio(tmp_path, monkeypatch):
    """IPYD + '104' => carpetas bajo COMP/104 (naming _COMP_SAMAN_SE)."""
    _so_macos(monkeypatch)
    ep = carpeta_comp(tmp_path, "IPYD/COMP/104")
    carpeta_comp(ep, "IPYD_104_010_COMP_SAMAN_SE")
    cfg = config_con_proyectos(tmp_path)

    planos = layouts.resolver_planos("104", "IPYD", cfg)

    assert planos == ["IPYD/COMP/104/IPYD_104_010_COMP_SAMAN_SE"]


def test_resolver_planos_proyecto_no_habilitado_aborta(tmp_path, monkeypatch):
    """PCF no habilitado en proyectos => abort nombrando el proyecto."""
    _so_macos(monkeypatch)
    cfg = config_con_proyectos(tmp_path, habilitados={"HTLR": True})

    with pytest.raises(SystemExit) as exc:
        layouts.resolver_planos("SC13", "PCF", cfg)

    mensaje = str(exc.value.code)
    assert "PCF" in mensaje
    assert "proyectos" in mensaje


def test_resolver_planos_episodio_sin_numero_aborta(tmp_path, monkeypatch):
    """Intencion sin episodio numerico (HTLR) => abort claro."""
    _so_macos(monkeypatch)
    cfg = config_con_proyectos(tmp_path)

    with pytest.raises(SystemExit) as exc:
        layouts.resolver_planos("planeta", "HTLR", cfg)

    assert "episodio" in str(exc.value.code)


def test_episodio_por_proyecto():
    """Los callables episodio remapean cada patron de proyecto (D1)."""
    assert HTLR.episodio("Capitulo 7") == "EP_07"
    assert HTLR.episodio("2VFX/Capitulo_12") == "EP_12"
    assert PCF.episodio("SC13") == "PFC_SC13"
    assert PCF.episodio("PFC_SC13") == "PFC_SC13"  # idempotente
    assert IPYD.episodio("104") == "104"


# ---------------------------------------------------------------------------
# RC-CN-05: los layouts son datos relativos (sin raices absolutas)
# ---------------------------------------------------------------------------


def test_layouts_son_relativos_sin_raices_absolutas():
    """Cada layout declara patrones relativos, con placeholder de fecha."""
    for nombre, layout in layouts.LAYOUTS.items():
        assert not layout.raiz.startswith("/"), nombre
        assert not layout.raiz.startswith("\\"), nombre
        assert "{fecha}" in layout.plate, nombre
        assert layout.patron_comp, nombre


# ---------------------------------------------------------------------------
# RC-QC-01: localizar_plate por fecha mas reciente (fecha_key)
# ---------------------------------------------------------------------------


def test_fecha_key_20260628_2_mas_reciente_que_20260627():
    """fecha_key ordena 20260628-2 > 20260628 > 20260627."""
    assert layouts.fecha_key("20260628-2") > layouts.fecha_key("20260627")
    assert layouts.fecha_key("20260628-2") > layouts.fecha_key("20260628")
    assert layouts.fecha_key("20260628") > layouts.fecha_key("20260627")


def test_localizar_plate_fecha_mas_reciente_gana(tmp_path, monkeypatch):
    """HTLR: la fecha mas reciente (20260628-2) gana a 20260627."""
    _so_macos(monkeypatch)
    base = tmp_path / "HTLR" / "TO_VFX" / "EP_07"
    (base / "20260627").mkdir(parents=True)
    (base / "20260628-2").mkdir()
    tocar(base / "20260627" / "plan_alpha_comp_SAMAN_V001.mov", time.time())
    tocar(base / "20260628-2" / "plan_alpha_comp_SAMAN_V001.mov", time.time())
    cfg = config_con_proyectos(tmp_path)
    plano = "HTLR/COMP/EP_07/plan_alpha_comp_SAMAN_V001"

    placa = layouts.localizar_plate(HTLR, plano, cfg)

    assert placa == "HTLR/TO_VFX/EP_07/20260628-2/plan_alpha_comp_SAMAN_V001.mov"


def test_localizar_plate_override_elige_fecha_vieja(tmp_path, monkeypatch):
    """Override de fecha (--plate-date) elige la vieja (RC-QC-01)."""
    _so_macos(monkeypatch)
    base = tmp_path / "HTLR" / "TO_VFX" / "EP_07"
    (base / "20260627").mkdir(parents=True)
    (base / "20260628-2").mkdir()
    tocar(base / "20260627" / "plan_alpha_comp_SAMAN_V001.mov", time.time())
    tocar(base / "20260628-2" / "plan_alpha_comp_SAMAN_V001.mov", time.time())
    cfg = config_con_proyectos(tmp_path)
    plano = "HTLR/COMP/EP_07/plan_alpha_comp_SAMAN_V001"

    placa = layouts.localizar_plate(HTLR, plano, cfg, fecha="20260627")

    assert placa == "HTLR/TO_VFX/EP_07/20260627/plan_alpha_comp_SAMAN_V001.mov"


def test_localizar_plate_sin_fecha_aborta_nombrando_la_ruta(tmp_path, monkeypatch):
    """Sin carpeta de fecha de plate => SinPlateError con la ruta."""
    _so_macos(monkeypatch)
    (tmp_path / "HTLR" / "TO_VFX" / "EP_07").mkdir(parents=True)
    cfg = config_con_proyectos(tmp_path)
    plano = "HTLR/COMP/EP_07/plan_alpha_comp_SAMAN_V001"

    with pytest.raises(layouts.SinPlateError) as exc:
        layouts.localizar_plate(HTLR, plano, cfg)

    assert "HTLR/TO_VFX/EP_07" in str(exc.value)


# ---------------------------------------------------------------------------
