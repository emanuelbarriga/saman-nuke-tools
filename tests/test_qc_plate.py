"""Tests del gate QC pre-render (PR3, D3/D5/D6): plate_qc + localizar_plate.

Cubren RC-QC-01/02/03/04:

- ``probar_plate``: parse de fixture JSON de ffprobe (ProRes 4444 / 10-bit /
  1920x1080 / 23.976 / 1665); fallo de probe o parse aborta nombrando la
  ruta (RC-QC-02); argv como lista, sin shell, ruta como argv (threat matrix
  'ffprobe subprocess').
- ``localizar_plate``: fecha_key ``20260628-2`` > ``20260627`` y override
  ``--plate-date`` que elige la fecha vieja (RC-QC-01).
- ``comparar``: fps 24 vs 23.976 => error; drift de preview REC709 (1558 vs
  1665) => warning; naming roto => error con decision; duracion delivery =>
  error (RC-QC-03).
- ``resolver_gate``: sin --force-qc aborta exit 3 con decision; --force-qc
  procede; --validar-solo-duracion y --fps-forzar resuelven (RC-QC-03/04).
- Reporte D6: ``contenido_reporte`` / ``resumen_reporte`` / ``reportar``.
- Decision D5: ``__DECISION__`` JSON; sin TTY (EOFError) => None (exit 3 auto).

Sin Nuke: ffprobe se reemplaza por monkeypatch de ``subprocess.run`` con
fixture; las rutas son relativas ficticias sobre tmp_path.
"""

import json
import os
import subprocess
import time

import pytest

from render_distribuido import layouts
from render_distribuido import plate_qc

HTLR = layouts.LAYOUTS["HTLR"]

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

# Fixture de ffprobe real (EP_108 HTLR_108_034): ProRes 4444 10-bit,
# 1920x1080 (spec), 24000/1001 ~ 23.976, 69.444375 s => 1665 frames.
FIXTURE_PROBE = {
    "streams": [
        {
            "codec_name": "prores",
            "codec_long_name": "Apple ProRes 4444",
            "pix_fmt": "yuv444p10le",
            "width": 1920,
            "height": 1080,
            "r_frame_rate": "24000/1001",
            "color_space": "bt709",
        }
    ],
    "format": {"duration": "69.444375"},
}


def probe_completed(fixture, rc=0, stderr=""):
    """CompletedProcess simulado del ffprobe (monkeypatch de subprocess.run)."""
    return subprocess.CompletedProcess(
        ["ffprobe"], rc, stdout=json.dumps(fixture), stderr=stderr
    )


def plate_fixture(
    ruta="HTLR/TO_VFX/EP_07/20260628/plan_alpha_comp_SAMAN_V001.mov",
    fps=23.976023976,
    width=2048,
    height=1156,
    frames=1665,
):
    """Dict de plate tal como lo devuelve probar_plate (sin los campos None)."""
    return {
        "ruta": ruta,
        "codec": "prores",
        "bit_depth": 12,
        "colorspace": "bt709",
        "width": width,
        "height": height,
        "fps": fps,
        "frames": frames,
        "duration": 69.444375,
        "r_frame_rate": "24000/1001",
    }


def config_con_proyectos(tmp_path):
    """Config ficticia: base local = tmp_path, proyectos habilitados."""
    return {"bases_por_so": {"macOS": str(tmp_path)}, "proyectos": {"HTLR": True}}


def _so_macos(monkeypatch):
    monkeypatch.setattr(layouts.platform, "system", lambda: "Darwin")


def tocar(archivo, mtime):
    """Escribe el archivo (si no existe) y fija su mtime real."""
    if not os.path.exists(archivo):
        import pathlib

        pathlib.Path(archivo).write_text("x", encoding="utf-8")
    os.utime(archivo, (mtime, mtime))


# ---------------------------------------------------------------------------
# RC-QC-02: probar_plate (ffprobe argv-list + parse de fixture JSON)
# ---------------------------------------------------------------------------


def test_probar_plate_parsea_fixture_prores_4444(monkeypatch):
    """ProRes 4444 / 10-bit / 1920x1080 / 23.976 / 1665 desde el fixture."""
    captura = {}

    def fake_run(argv, **kw):
        captura["argv"] = argv
        captura["shell"] = kw.get("shell")
        return probe_completed(FIXTURE_PROBE)

    monkeypatch.setattr(plate_qc.subprocess, "run", fake_run)

    plate = plate_qc.probar_plate(
        "HTLR/TO_VFX/EP_07/20260628/plan_alpha_comp_SAMAN_V001.mov"
    )

    assert plate["codec"] == "prores"
    assert plate["bit_depth"] == 10
    assert plate["colorspace"] == "bt709"
    assert (plate["width"], plate["height"]) == (1920, 1080)
    assert round(plate["fps"], 3) == 23.976
    assert plate["frames"] == 1665
    # threat 'ffprobe subprocess': argv como lista, sin shell, ruta como argv
    assert captura["argv"][0] == "ffprobe"
    assert captura["shell"] is False
    assert "HTLR/TO_VFX/EP_07/20260628/plan_alpha_comp_SAMAN_V001.mov" in captura["argv"]


def test_probar_plate_fallo_aborta_nombrando_la_ruta(monkeypatch):
    """Probe con returncode != 0 => ProbeError nombrando la ruta (RC-QC-02)."""

    def fake_run(argv, **kw):
        return probe_completed({}, rc=1, stderr="No such file or directory")

    monkeypatch.setattr(plate_qc.subprocess, "run", fake_run)

    with pytest.raises(plate_qc.ProbeError) as exc:
        plate_qc.probar_plate("HTLR/TO_VFX/EP_07/plate_missing.mov")

    assert "HTLR/TO_VFX/EP_07/plate_missing.mov" in str(exc.value)


def test_probar_plate_salida_no_json_aborta(monkeypatch):
    """stdout no parseable => ProbeError (nunca un default silencioso)."""

    def fake_run(argv, **kw):
        return probe_completed("esto no es json", rc=0)

    monkeypatch.setattr(plate_qc.subprocess, "run", fake_run)

    with pytest.raises(plate_qc.ProbeError):
        plate_qc.probar_plate("HTLR/TO_VFX/EP_07/plan.mov")


def test_probar_plate_sin_stream_de_video_aborta(monkeypatch):
    """JSON sin streams => ProbeError (metadata incompleta)."""

    def fake_run(argv, **kw):
        return probe_completed({"streams": [], "format": {"duration": "1.0"}})

    monkeypatch.setattr(plate_qc.subprocess, "run", fake_run)

    with pytest.raises(plate_qc.ProbeError):
        plate_qc.probar_plate("HTLR/TO_VFX/EP_07/plan.mov")


def test_fps_desde_racional_24000_1001_es_23976():
    """24000/1001 => 23.9760239... (el caso 24 vs 23.976 del spec)."""
    fps = plate_qc.fps_desde_racional("24000/1001")
    assert round(fps, 3) == 23.976
    assert round(plate_qc.fps_desde_racional("24"), 3) == 24.0
    assert round(plate_qc.fps_desde_racional("23.976"), 3) == 23.976
    assert plate_qc.fps_desde_racional("0/1") is None
    assert plate_qc.fps_desde_racional("x/y") is None


def test_frames_desde_duracion_redondea():
    """69.444375 s x 23.976 => 1665 redondeado (duracion -> frames)."""
    assert plate_qc.frames_desde_duracion("69.444375", 24000 / 1001) == 1665
    assert plate_qc.frames_desde_duracion(65.0, 23.976) == 1558  # drift REC709


def test_bit_depth_desde_pix_fmt():
    """yuv444p10le => 10; yuv444p12le => 12; desconocido => None."""
    assert plate_qc.bit_depth_desde_pix_fmt("yuv444p10le") == 10
    assert plate_qc.bit_depth_desde_pix_fmt("yuv444p12le") == 12
    assert plate_qc.bit_depth_desde_pix_fmt("yuv420p") is None


# ---------------------------------------------------------------------------
# RC-QC-01: localizar_plate (fecha_key + override --plate-date)
# ---------------------------------------------------------------------------


def test_fecha_key_20260628_2_mas_reciente_que_20260627():
    """fecha_key ordena 20260628-2 > 20260628 > 20260627 (RC-QC-01)."""
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
# normalizar_id_plano: emparejamiento plate <-> nodo de entrega (RC-QC-03)
# ---------------------------------------------------------------------------


def test_normalizar_id_plano_quita_sufijos_del_pipeline():
    """Se quitan _comp_SAMAN(_SE) y _V\\d+; el core del plano queda intacto."""
    assert plate_qc.normalizar_id_plano("plan_alpha_comp_SAMAN_V001.mov") == "plan_alpha"
    assert plate_qc.normalizar_id_plano("plan_002_comp_SAMAN_V001.nk") == "plan_002"
    assert plate_qc.normalizar_id_plano("plan_alpha_comp_SAMAN_V001.0100.exr") == "plan_alpha"
    assert plate_qc.normalizar_id_plano("plan_alpha_comp_SAMAN_se.nk") == "plan_alpha"
    # numeros de frame/placeholders y V01_0100 reales del naming no se tocan
    assert plate_qc.normalizar_id_plano("HTLR_108_034_V01_0100.mov") == "HTLR_108_034_V01_0100"
    assert plate_qc.normalizar_id_plano("HTLR_108_034_V01_0100.####.exr") == "HTLR_108_034_V01_0100"
    assert plate_qc.normalizar_id_plano("HTLR_108_034_V01_0100.0100.exr") == "HTLR_108_034_V01_0100"


# ---------------------------------------------------------------------------
# RC-QC-03: comparar plate vs root vs nodos (severidad warning|error)
# ---------------------------------------------------------------------------


def test_comparar_fps_24_vs_23976_error():
    """Comp a 24 fps vs plate a 23.976 => discrepancia ERROR tipo fps."""
    plate = plate_fixture()
    root = {"fps": 24.0, "first": 1, "last": 1665, "width": 2048, "height": 1156}

    disc = plate_qc.comparar(plate, root, {})

    fps_err = [d for d in disc if d["tipo"] == "fps"]
    assert len(fps_err) == 1
    assert fps_err[0]["severidad"] == "error"
    assert fps_err[0]["campo"] == "fps"
    assert round(fps_err[0]["esperado"], 3) == 23.976
    assert fps_err[0]["encontrado"] == 24.0


def test_comparar_sin_fps_error_cuando_coinciden():
    """Root 23.976 redondeado == plate 23.976 => sin discrepancia de fps."""
    plate = plate_fixture()
    root = {"fps": 23.976, "first": 1, "last": 1665, "width": 2048, "height": 1156}

    disc = plate_qc.comparar(plate, root, {})

    assert [d for d in disc if d["tipo"] == "fps"] == []


def test_comparar_preview_drift_1558_vs_1665_warning():
    """Drift SOLO en preview REC709 (1558 vs 1665) => warning, no abort (RC-QC-03)."""
    plate = plate_fixture()
    root = {"fps": 23.976, "first": 1, "last": 1665, "width": 2048, "height": 1156}
    nodos = {
        "REVIEW_REC709": {
            "first": 1001,
            "last": 2558,  # 1558 frames
            "file": "/b/HTLR/FROM_VFX/EP_07/20260628/REVIEW_REC709/review.mov",
        }
    }

    disc = plate_qc.comparar(plate, root, nodos)

    dur = [d for d in disc if d["tipo"] == "duracion" and d["nodo"] == "REVIEW_REC709"]
    assert len(dur) == 1
    assert dur[0]["severidad"] == "warning"
    assert dur[0]["encontrado"] == 1558


def test_comparar_duracion_delivery_error():
    """Nodo de entrega DELIVERY_EXR con rango distinto al plate => error."""
    plate = plate_fixture()
    root = {"fps": 23.976, "first": 1, "last": 1665, "width": 2048, "height": 1156}
    nodos = {
        "DELIVERY_EXR": {
            "first": 1,
            "last": 1558,  # 1558 != 1665
            "file": "/b/HTLR/FROM_VFX/EP_07/20260628/DELIVERY_EXR/"
                    "plan_alpha_comp_SAMAN_V001.####.exr",
        }
    }

    disc = plate_qc.comparar(plate, root, nodos)

    dur = [d for d in disc if d["tipo"] == "duracion" and d["nodo"] == "DELIVERY_EXR"]
    assert len(dur) == 1
    assert dur[0]["severidad"] == "error"


def test_comparar_resolucion_distinta_error():
    """Root con format distinto al plate => discrepancia ERROR resolucion."""
    plate = plate_fixture()
    root = {"fps": 23.976, "first": 1, "last": 1665, "width": 1920, "height": 1080}

    disc = plate_qc.comparar(plate, root, {})

    res = [d for d in disc if d["tipo"] == "resolucion"]
    assert len(res) == 1
    assert res[0]["severidad"] == "error"
    assert res[0]["esperado"] == "2048x1156"
    assert res[0]["encontrado"] == "1920x1080"


def test_comparar_naming_roto_error():
    """Nodo delivery que no empareja por naming => error con decision (RC-QC-03)."""
    plate = plate_fixture()
    root = {"fps": 23.976, "first": 1, "last": 1665, "width": 2048, "height": 1156}
    nodos = {
        "DELIVERY_EXR": {
            "first": 1,
            "last": 1665,
            "file": "/b/HTLR/FROM_VFX/EP_07/20260628/DELIVERY_EXR/"
                    "plan_beta_comp_SAMAN_V003.0100.exr",  # otro plano
        }
    }

    disc = plate_qc.comparar(plate, root, nodos)

    naming = [d for d in disc if d["tipo"] == "naming"]
    assert len(naming) == 1
    assert naming[0]["severidad"] == "error"
    assert naming[0]["decision"] == "validar_solo_duracion"
    assert naming[0]["esperado"] == "plan_alpha"
    assert naming[0]["encontrado"] == "plan_beta"


def test_comparar_coincidencia_total_sin_discrepancias():
    """Plate == root == nodos: lista vacia (no hay falsos positivos)."""
    plate = plate_fixture()
    root = {"fps": 23.976, "first": 1, "last": 1665, "width": 2048, "height": 1156}
    nodos = {
        "DELIVERY_EXR": {
            "first": 1,
            "last": 1665,
            "file": "/b/HTLR/FROM_VFX/EP_07/20260628/DELIVERY_EXR/"
                    "plan_alpha_comp_SAMAN_V001.####.exr",
        },
        "REVIEW_REC709": {
            "first": 1,
            "last": 1665,
            "file": "/b/HTLR/FROM_VFX/EP_07/20260628/REVIEW_REC709/"
                    "plan_alpha_comp_SAMAN_V001.mov",
        },
    }

    assert plate_qc.comparar(plate, root, nodos) == []


# ---------------------------------------------------------------------------
# RC-QC-03/04: resolver_gate (abort exit 3 vs --force-qc vs overrides)
# ---------------------------------------------------------------------------


def test_resolver_gate_fps_mismatch_aborta_exit_3_con_decision():
    """FPS 24 vs 23.976 sin --force-qc => aborta exit 3 con decision (D5)."""
    plate = plate_fixture()
    root = {"fps": 24.0, "first": 1, "last": 1665, "width": 2048, "height": 1156}
    disc = plate_qc.comparar(plate, root, {})

    res = plate_qc.resolver_gate(disc)

    assert res["aborta"] is True
    assert res["exit"] == 3
    assert res["decision"]["id"] == "fps_mismatch"
    assert res["decision"]["opciones"] == ["forzar_fps", "cancelar"]
    assert res["decision"]["default"] == "cancelar"


def test_resolver_gate_force_qc_procede():
    """--force-qc => nunca aborta; las discrepancias quedan reportadas (RC-QC-04)."""
    plate = plate_fixture()
    root = {"fps": 24.0, "first": 1, "last": 1665, "width": 2048, "height": 1156}
    disc = plate_qc.comparar(plate, root, {})

    res = plate_qc.resolver_gate(disc, force_qc=True)

    assert res["aborta"] is False
    assert res["exit"] == 0


def test_resolver_gate_naming_roto_validar_solo_duracion_resuelve():
    """[Validar solo duracion] resuelve el naming roto; los demas errores pesan."""
    plate = plate_fixture()
    root = {"fps": 23.976, "first": 1, "last": 1665, "width": 2048, "height": 1156}
    nodos = {
        "DELIVERY_EXR": {
            "first": 1,
            "last": 1665,
            "file": "/b/HTLR/FROM_VFX/EP_07/20260628/DELIVERY_EXR/"
                    "plan_beta_comp_SAMAN_V003.0100.exr",
        }
    }
    disc = plate_qc.comparar(plate, root, nodos)

    assert plate_qc.resolver_gate(disc)["aborta"] is True
    resuelto = plate_qc.resolver_gate(disc, validar_solo_duracion=True)
    assert resuelto["aborta"] is False


def test_resolver_gate_fps_forzar_resuelve_fps():
    """--fps-forzar resuelve la discrepancia de fps (override no interactivo)."""
    plate = plate_fixture()
    root = {"fps": 24.0, "first": 1, "last": 1665, "width": 2048, "height": 1156}
    disc = plate_qc.comparar(plate, root, {})

    assert plate_qc.resolver_gate(disc)["aborta"] is True
    assert plate_qc.resolver_gate(disc, fps_forzar="23.976")["aborta"] is False


def test_resolver_gate_solo_warnings_no_aborta():
    """Drift en previews SOLO => warning, nunca abort (RC-QC-03)."""
    disc = [
        {"severidad": "warning", "tipo": "duracion", "nodo": "REVIEW_REC709",
         "campo": "frames", "esperado": 1665, "encontrado": 1558}
    ]

    res = plate_qc.resolver_gate(disc)

    assert res["aborta"] is False
    assert res["exit"] == 0


# ---------------------------------------------------------------------------
# D6: reporte JSON (TEST_RENDER/qc_<proyecto>_<ts>.json) + resumen stdout
# ---------------------------------------------------------------------------


def test_contenido_reporte_shape():
    """El payload del reporte sigue la forma D6 (proyecto/planos/plates/disc)."""
    payload = plate_qc.contenido_reporte(
        "HTLR",
        [{"plano": "HTLR/COMP/EP_07/plan_alpha", "version_elegida": "v001.nk",
          "mtime": 1234.5, "sospechosa": True, "candidatas": ["v001.nk"]}],
        [{"plano": "HTLR/COMP/EP_07/plan_alpha", "fecha": "20260628",
          "ruta_relativa": "HTLR/TO_VFX/EP_07/20260628/plan.mov",
          "ffprobe": {"codec": "prores", "bit_depth": 12, "colorspace": "bt709",
                      "res": "2048x1156", "fps": 23.976, "frames": 1665}}],
        [{"severidad": "warning", "tipo": "duracion", "nodo": "REVIEW_REC709",
          "campo": "frames", "esperado": 1665, "encontrado": 1558}],
    )

    assert set(payload) == {"proyecto", "planos", "plates", "discrepancias"}
    assert payload["proyecto"] == "HTLR"
    assert payload["plates"][0]["ffprobe"]["res"] == "2048x1156"
    assert payload["discrepancias"][0]["severidad"] == "warning"


def test_reportar_escribe_json_en_test_render(tmp_path):
    """Reporte en TEST_RENDER/qc_<proyecto>_*.json con el payload completo (D6)."""
    payload = plate_qc.contenido_reporte("HTLR", [], [],
                                         [{"severidad": "error", "tipo": "fps",
                                           "nodo": "root", "campo": "fps",
                                           "esperado": 23.976, "encontrado": 24.0}])

    ruta = plate_qc.reportar(str(tmp_path), payload)

    assert os.path.basename(ruta) == "qc_HTLR_" + os.path.basename(ruta).split("qc_HTLR_")[1]
    assert os.path.isfile(ruta)
    with open(ruta, encoding="utf-8") as fh:
        guardado = json.load(fh)
    assert guardado["proyecto"] == "HTLR"
    assert guardado["discrepancias"][0]["encontrado"] == 24.0


def test_resumen_reporte_lista_discrepancias():
    """El resumen stdout nombra severidad, tipo y valores esperado/encontrado."""
    payload = plate_qc.contenido_reporte(
        "HTLR", [], [],
        [{"severidad": "error", "tipo": "fps", "nodo": "root", "campo": "fps",
          "esperado": 23.976, "encontrado": 24.0}],
    )

    resumen = plate_qc.resumen_reporte(payload)

    assert "[error]" in resumen
    assert "fps" in resumen
    assert "23.976" in resumen and "24.0" in resumen


# ---------------------------------------------------------------------------
# D5: decision estructurada (__DECISION__ JSON; auto => None => exit 3)
# ---------------------------------------------------------------------------


def test_decision_imprime_json_y_devuelve_la_opcion(capsys):
    """En TTY imprime __DECISION__{id,problema,opciones,default} y lee (D5)."""
    eleccion = plate_qc.decision(
        "fps_mismatch", "fps del comp 24 vs plate 23.976",
        ["forzar_fps", "cancelar"], "cancelar",
        leer=lambda _: "forzar_fps",
    )

    assert eleccion == "forzar_fps"
    out = capsys.readouterr().out
    assert "__DECISION__" in out
    datos = json.loads(out.split("__DECISION__", 1)[1])
    assert datos["id"] == "fps_mismatch"
    assert datos["opciones"] == ["forzar_fps", "cancelar"]
    assert datos["default"] == "cancelar"


def test_decision_sin_tty_devuelve_none(capsys):
    """Sin TTY (EOFError) => None: el CLI aborta con exit 3 (modo auto)."""

    def leer_eof(_):
        raise EOFError

    eleccion = plate_qc.decision(
        "naming_roto", "plate no empareja por naming",
        ["validar_solo_duracion", "abortar"], "abortar", leer=leer_eof,
    )

    assert eleccion is None
    assert "__DECISION__" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# D3: spec_qc_set (reescritura del nodo delivery a las specs del plate)
# ---------------------------------------------------------------------------


def test_spec_qc_set_reescribe_delivery_a_specs_del_plate():
    """QC_SET sobre DELIVERY_EXR: fps/format/rango del plate (Regla de Oro)."""
    plate = plate_fixture()
    pr = {"plate_first": 1001, "plate_last": 2665}

    spec = plate_qc.spec_qc_set(plate, pr)

    assert spec == {
        "DELIVERY_EXR": {
            "fps": 23.976,
            "format": "2048x1156",
            "first": 1001,
            "last": 2665,
        }
    }


def test_spec_qc_set_sin_rango_del_plate_usa_1_a_frames():
    """Sin rango de plate en la PROBE => first=1, last=frames (fallback)."""
    plate = plate_fixture()
    spec = plate_qc.spec_qc_set(plate, {})

    assert spec["DELIVERY_EXR"]["first"] == 1
    assert spec["DELIVERY_EXR"]["last"] == 1665


def test_spec_qc_set_fps_forzar_domina():
    """--fps-forzar define el fps del QC_SET en lugar del del plate."""
    plate = plate_fixture()
    spec = plate_qc.spec_qc_set(plate, {}, fps_diana=24.0)

    assert spec["DELIVERY_EXR"]["fps"] == 24.0