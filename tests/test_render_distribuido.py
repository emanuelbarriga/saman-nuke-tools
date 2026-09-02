"""Tests de render_distribuido.render_distribuido (orquestador config-driven).

El orquestador ya NO hardcodea infraestructura del estudio (IPs, usuarios,
bases por SO, sufijos): la lee de la config central via
``render_config.obtener_config_efectiva()``. Estos tests verifican las
funciones puras que transforman la config en workers/sufijos internos, la
traduccion cross-SO de templates (``template_local`` por ``traducir_ruta``) y
que el modulo no contenga datos reales del estudio.

Todas las rutas/workers son ficticios (hostnames, sin IPs). No dependen de
Nuke ni de la unidad montada.
"""

import argparse
import json
import os
import platform
import re
import subprocess
from pathlib import Path

import pytest

from render_distribuido import layouts
from render_distribuido import plate_qc
from render_distribuido import render_distribuido as orquestador

RUTA_ORQUESTADOR = (
    Path(__file__).resolve().parent.parent
    / "render_distribuido"
    / "render_distribuido.py"
)


def config_workers():
    """Workers ficticios conforme al esquema (hostnames, sin IPs ni usuarios reales)."""
    return {
        "workers": [
            {
                "nombre": "imac",
                "ssh": None,
                "ssh_user": "artista",
                "nuke_exec": "/Programas/Nuke17.1v1/Nuke17.1",
                "base": "/Volumes/wupm/2026",
                "lc_all": False,
            },
            {
                "nombre": "vfxserver",
                "ssh": "vfxserver.studio.local",
                "ssh_user": "usuario_render",
                "nuke_exec": "/opt/Nuke17.1v1/Nuke17.1",
                "base": "/media/wupm/2026",
                "lc_all": True,
            },
        ]
    }


def config_bases():
    """Bases por SO ficticias (sin la base real del estudio)."""
    return {
        "bases_por_so": {
            "macOS": "/Volumes/wupm/2026",
            "Linux": "/media/wupm/2026",
            "Windows": "W:\\wupm\\2026",
        }
    }


# ---------------------------------------------------------------------------
# construir_workers: workers internos desde la config (spec: Workers from config)
# ---------------------------------------------------------------------------


def test_construir_workers_remoto_compone_ssh_y_nuke_exec():
    """Worker remoto: ssh = ssh_user + host, bin = nuke_exec, base y lc_all."""
    workers = orquestador.construir_workers(config_workers()["workers"])
    remoto = [w for w in workers if w["nombre"] == "vfxserver"][0]
    assert remoto["ssh"] == "usuario_render" + "@" + "vfxserver.studio.local"
    assert remoto["bin"] == "/opt/Nuke17.1v1/Nuke17.1"
    assert remoto["base"] == "/media/wupm/2026"
    assert remoto["lc_all"] is True


def test_construir_workers_local_queda_sin_ssh():
    """Worker local (ssh None): ssh queda None y bin sale de nuke_exec."""
    workers = orquestador.construir_workers(config_workers()["workers"])
    local = [w for w in workers if w["nombre"] == "imac"][0]
    assert local["ssh"] is None
    assert local["bin"] == "/Programas/Nuke17.1v1/Nuke17.1"
    assert local["base"] == "/Volumes/wupm/2026"
    assert local["lc_all"] is False


# ---------------------------------------------------------------------------
# filtrar_por_nombre: --workers filtra, None/vacio => todos
# ---------------------------------------------------------------------------


def test_filtrar_sin_pedido_devuelve_todos():
    """--workers ausente (None o vacio) => todos los workers de la config."""
    workers = orquestador.construir_workers(config_workers()["workers"])
    assert [w["nombre"] for w in orquestador.filtrar_por_nombre(workers, None)] == [
        "imac", "vfxserver",
    ]
    assert [w["nombre"] for w in orquestador.filtrar_por_nombre(workers, "")] == [
        "imac", "vfxserver",
    ]


def test_filtrar_por_uno_selecciona_solo_ese():
    """--workers vfxserver => exactamente ese worker, sin el resto."""
    workers = orquestador.construir_workers(config_workers()["workers"])
    seleccion = orquestador.filtrar_por_nombre(workers, "vfxserver")
    assert [w["nombre"] for w in seleccion] == ["vfxserver"]


def test_filtrar_varios_preserva_el_orden_de_la_config():
    """--workers con varios nombres => orden de la config, sin duplicados."""
    workers = orquestador.construir_workers(config_workers()["workers"])
    seleccion = orquestador.filtrar_por_nombre(workers, "imac, vfxserver")
    assert [w["nombre"] for w in seleccion] == ["imac", "vfxserver"]


def test_filtrar_nombre_inexistente_devuelve_vacio():
    """Nombre que no esta en la config => lista vacia (no falla)."""
    workers = orquestador.construir_workers(config_workers()["workers"])
    assert orquestador.filtrar_por_nombre(workers, "workerfantasma") == []


# ---------------------------------------------------------------------------
# sufijos_efectivos: defaults desde la config, CLI sobreescribe (spec:
# Suffix defaults from config)
# ---------------------------------------------------------------------------


def test_sufijos_defaults_vienen_de_la_config():
    """Sin flags: TO_SUF/COMP_SUF/FROM_SUF toman los sufijos de la config."""
    sufijos = {"TO_VFX": "/TO/", "COMP": "/COMP/", "FROM_VFX": "/FROM_VFX/"}
    efectivos = orquestador.sufijos_efectivos(sufijos, None, None, None)
    assert efectivos == {
        "TO_SUF": "/TO/",
        "COMP_SUF": "/COMP/",
        "FROM_SUF": "/FROM_VFX/",
    }


def test_sufijos_cli_sobreescriben_a_la_config():
    """Flags explicitos ganan a los defaults de la config."""
    sufijos = {"TO_VFX": "/TO/", "COMP": "/COMP/", "FROM_VFX": "/FROM_VFX/"}
    efectivos = orquestador.sufijos_efectivos(
        sufijos, "/MI_TO/", "/MI_COMP/", "/MI_FROM/"
    )
    assert efectivos == {
        "TO_SUF": "/MI_TO/",
        "COMP_SUF": "/MI_COMP/",
        "FROM_SUF": "/MI_FROM/",
    }


def test_sufijos_override_parcial_mezcla_cli_y_config():
    """Solo un flag: ese gana, los otros dos salen de la config."""
    sufijos = {"TO_VFX": "/TO/", "COMP": "/COMP/", "FROM_VFX": "/FROM_VFX/"}
    efectivos = orquestador.sufijos_efectivos(sufijos, None, "/X/", None)
    assert efectivos["TO_SUF"] == "/TO/"
    assert efectivos["COMP_SUF"] == "/X/"
    assert efectivos["FROM_SUF"] == "/FROM_VFX/"


def test_env_worker_lleva_el_sufijo_de_config_al_env():
    """El env del worker expone TO_SUF/COMP_SUF/FROM_SUF resueltos (contrato D6)."""
    args = argparse.Namespace(
        comp="TEST_RENDER/prueba_test.nk",
        wnode="Write1",
        to_suf="/TO/",
        comp_suf="/COMP/",
        from_suf="/FROM_VFX/",
    )
    env = orquestador.env_worker({"base": "/Volumes/wupm/2026"}, args, "render")
    assert env["TO_SUF"] == "/TO/"
    assert env["COMP_SUF"] == "/COMP/"
    assert env["FROM_SUF"] == "/FROM_VFX/"
    assert env["MODE"] == "render"
    assert env["BASE"] == "/Volumes/wupm/2026"


# ---------------------------------------------------------------------------
# template_local: traduccion cross-SO via traducir_ruta (spec: Multi-OS path
# translation aplicada a la deteccion de frames existentes)
# ---------------------------------------------------------------------------


def test_template_linux_se_traduce_a_la_base_local_macos(monkeypatch):
    """Template reportado en base Linux se detecta y traduce a la base macOS."""
    monkeypatch.setattr(orquestador, "so_local", lambda: "macOS")
    template = "/media/wupm/2026/PCF/TO_VFX/comp_SAMAN_V05.####.exr"
    traducido = orquestador.template_local(template, config_bases())
    assert traducido == "/Volumes/wupm/2026/PCF/TO_VFX/comp_SAMAN_V05.####.exr"


def test_template_windows_se_traduce_a_la_base_local_macos(monkeypatch):
    """Template Windows (backslashes) se normaliza hacia la base macOS local."""
    monkeypatch.setattr(orquestador, "so_local", lambda: "macOS")
    template = "W:\\wupm\\2026\\PCF\\TO_VFX\\comp_V03.####.exr"
    traducido = orquestador.template_local(template, config_bases())
    assert traducido == "/Volumes/wupm/2026/PCF/TO_VFX/comp_V03.####.exr"


def test_template_en_la_base_local_queda_intacto(monkeypatch):
    """Template ya en la base local: no se toca."""
    monkeypatch.setattr(orquestador, "so_local", lambda: "macOS")
    template = "/Volumes/wupm/2026/PCF/TO_VFX/comp_V05.####.exr"
    assert orquestador.template_local(template, config_bases()) == template


def test_template_fuera_de_prefijos_declarados_queda_intacto(monkeypatch):
    """Prefijo no declarado en bases_por_so: intacto (spec: Unknown prefix)."""
    monkeypatch.setattr(orquestador, "so_local", lambda: "macOS")
    template = "/otros/wupm/2026/PCF/to_vfx/comp_V05.####.exr"
    assert orquestador.template_local(template, config_bases()) == template


def test_template_vacio_devuelve_none():
    """Sin template (probe sin Write): None directo, sin traduccion."""
    assert orquestador.template_local(None, config_bases()) is None
    assert orquestador.template_local("", config_bases()) == ""


# ---------------------------------------------------------------------------
# so_local: el SO de la maquina del orquestador con la clave del esquema
# ---------------------------------------------------------------------------


def test_so_local_mapa_platform_a_claves_del_esquema(monkeypatch):
    """Darwin/Linux/Windows se mapean a las claves macOS/Linux/Windows."""
    for sistema, esperado in {
        "Darwin": "macOS",
        "Linux": "Linux",
        "Windows": "Windows",
    }.items():
        monkeypatch.setattr(platform, "system", lambda: sistema)
        assert orquestador.so_local() == esperado


# ---------------------------------------------------------------------------
# ejecutar: env EXPLICITO en el argv remoto (D6, threat matrix: Remote
# command/env composition) — sin depender de AcceptEnv de sshd
# ---------------------------------------------------------------------------


def test_ejecutar_remoto_compone_env_explicito_en_argv(monkeypatch):
    """El argv remoto lleva 'env KEY='val' ...' inline (D6), sin shell local."""
    llamadas = []

    def fake_run(cmd, **kw):
        llamadas.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(orquestador.subprocess, "run", fake_run)
    worker = {
        "nombre": "vfxserver",
        "ssh": "render_user" + "@" + "vfxserver.studio.local",
        "bin": "/opt/Nuke18.0v1/Nuke18.0",
        "base": "/media/wupm/2026",
        "lc_all": True,
    }
    env = {"TO_SUF": "/TO/", "COMP_SUF": "/COMP/"}

    orquestador.ejecutar(
        worker,
        ["/opt/Nuke18.0v1/Nuke18.0", "-t", "render_worker.py"],
        env,
        timeout=30,
    )

    cmd, kwargs = llamadas[0]
    assert cmd[0] == "ssh"
    assert "BatchMode=yes" in cmd
    assert worker["ssh"] in cmd  # ssh_user + host ya compuesto en Python
    token_env = next(t for t in cmd if t.startswith("env "))
    assert "LC_ALL=C" in token_env  # prefijo Linux del worker (lc_all)
    assert "TO_SUF='/TO/'" in token_env
    assert "COMP_SUF='/COMP/'" in token_env
    assert "-t" in token_env and "render_worker.py" in token_env  # argv remoto
    assert not kwargs.get("shell")  # nunca un shell local (threat matrix)


def test_ejecutar_local_pasa_argv_sin_env_ni_ssh(monkeypatch):
    """Worker local (ssh None): argv directo a subprocess, sin ssh ni env."""
    llamadas = []

    def fake_run(cmd, **kw):
        llamadas.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(orquestador.subprocess, "run", fake_run)
    worker = {
        "nombre": "macpro",
        "ssh": None,
        "bin": "/Programas/Nuke18.0v1/Nuke18.0",
        "base": "/Volumes/wupm/2026",
        "lc_all": False,
    }
    argv = ["/Programas/Nuke18.0v1/Nuke18.0", "-t", "render_worker.py"]

    orquestador.ejecutar(worker, argv, {"TO_SUF": "/TO/"}, timeout=30)

    assert llamadas[0] == argv
    assert all("env " not in t for t in llamadas[0])


# ---------------------------------------------------------------------------
# Multi-nodo (PR2): env WNODES/PIGGYBACK/FORCE_EXR (D4, threat Remote
# command/env composition extendido)
# ---------------------------------------------------------------------------


def test_env_worker_multi_nodo_lleva_wnodes_y_piggyback_al_env():
    """El env del worker expone WNODES/PIGGYBACK en modo render (D6/D4)."""
    args = argparse.Namespace(
        comp="HTLR/COMP/EP_07/plan_alpha_comp_SAMAN_V001/plan_comp_SAMAN_v001.nk",
        wnode="DELIVERY_EXR",
        wnodes="DELIVERY_EXR,REVIEW_REC709",
        piggyback="REVIEW_REC709:1558:1665",
        force_exr=False,
        to_suf="/TO/",
        comp_suf="/COMP/",
        from_suf="/FROM_VFX/",
    )
    env = orquestador.env_worker({"base": "/Volumes/wupm/2026"}, args, "render")

    assert env["WNODES"] == "DELIVERY_EXR,REVIEW_REC709"
    assert env["PIGGYBACK"] == "REVIEW_REC709:1558:1665"
    assert env["WNODE"] == "DELIVERY_EXR"
    assert "FORCE_EXR" not in env  # flag inactivo


def test_env_worker_force_exr_solo_en_render(monkeypatch):
    """FORCE_EXR se emite en render; no en probe (calib sin forzar)."""
    args = argparse.Namespace(
        comp="x.nk", wnode="DELIVERY_EXR", wnodes=None, piggyback=None,
        force_exr=True, to_suf=None, comp_suf=None, from_suf=None,
    )
    env_render = orquestador.env_worker({"base": "/b"}, args, "render")
    env_probe = orquestador.env_worker({"base": "/b"}, args, "probe")

    assert env_render["FORCE_EXR"] == "1"
    assert "FORCE_EXR" not in env_probe
    assert "PIGGYBACK" not in env_probe


def test_ejecutar_remoto_quoting_wnodes_y_piggyback_intacto(monkeypatch):
    """env KEY='val' con WNODES/PIGGYBACK integros en el argv remoto (D6)."""
    llamadas = []

    def fake_run(cmd, **kw):
        llamadas.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(orquestador.subprocess, "run", fake_run)
    worker = {
        "nombre": "vfxserver",
        "ssh": "render_user" + "@" + "vfxserver.studio.local",
        "bin": "/opt/Nuke18.0v1/Nuke18.0",
        "base": "/media/wupm/2026",
        "lc_all": True,
    }
    env = {
        "WNODES": "DELIVERY_EXR,REVIEW_REC709",
        "PIGGYBACK": "REVIEW_REC709:1558:1665",
    }

    orquestador.ejecutar(
        worker, ["/opt/Nuke18.0v1/Nuke18.0", "-t", "render_worker.py"], env, timeout=30
    )

    cmd, kwargs = llamadas[0]
    token_env = next(t for t in cmd if t.startswith("env "))
    assert "WNODES='DELIVERY_EXR,REVIEW_REC709'" in token_env
    assert "PIGGYBACK='REVIEW_REC709:1558:1665'" in token_env
    assert not kwargs.get("shell")


def test_env_con_metacaracteres_queda_inerte_en_el_argv(monkeypatch):
    """Valor de env con metacaracteres shell: quoted => inerte (threat env).

    Ademas, un nombre de nodo con metacaracteres jamas cruza el filtro
    --wnodes (filtrar_wnodes), asi que no llega a componerse como nombre.
    """
    llamadas = []

    def fake_run(cmd, **kw):
        llamadas.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(orquestador.subprocess, "run", fake_run)
    worker = {
        "nombre": "vfxserver",
        "ssh": "render_user" + "@" + "vfxserver.studio.local",
        "bin": "/opt/Nuke18.0v1/Nuke18.0",
        "base": "/media/wupm/2026",
        "lc_all": False,
    }
    malicioso = "DELIVERY_EXR;touch /tmp/x"
    orquestador.ejecutar(
        worker, ["/opt/Nuke18.0v1/Nuke18.0", "-t", "render_worker.py"],
        {"WNODES": malicioso, "PIGGYBACK": "REVIEW_REC709;id"}, timeout=30,
    )

    token_env = next(t for t in llamadas[0] if t.startswith("env "))
    # single quotes: los metacaracteres son parte del VALOR, no del shell
    assert "WNODES='DELIVERY_EXR;touch /tmp/x'" in token_env
    assert "PIGGYBACK='REVIEW_REC709;id'" in token_env


# ---------------------------------------------------------------------------
# Gate QC pre-render (PR3, D3/D5/D6, RC-QC-04): wiring PROBE -> QC -> reporte
# ---------------------------------------------------------------------------


def _args_qc(**opciones):
    """Namespace del flujo asistido con los flags QC (defaults apagados)."""
    base = {
        "proyecto": "HTLR",
        "comp_dir": None,
        "resolve_latest": True,
        "use_version": None,
        "force_qc": False,
        "plate_date": None,
        "validar_solo_duracion": False,
        "fps_forzar": None,
    }
    base.update(opciones)
    return argparse.Namespace(**base)


def _config_qc(tmp_path):
    """Config ficticia con base = tmp_path para la resolucion de rutas."""
    return {
        "bases_por_so": {"macOS": str(tmp_path)},
        "proyectos": {"HTLR": True},
    }


def _plano_fixture(tmp_path):
    """Crea el layout ficticio HTLR (plate + comp) bajo tmp_path y devuelve
    (plano, version, pr) con la PROBE del EP_108 real (root 24fps, preview
    REC709 con drift 1558 vs plate 1665)."""
    if not os.path.isdir(tmp_path / "HTLR" / "TO_VFX" / "EP_07" / "20260628"):
        (tmp_path / "HTLR" / "TO_VFX" / "EP_07" / "20260628").mkdir(parents=True)
        (tmp_path / "HTLR" / "TO_VFX" / "EP_07" / "20260628"
         / "plan_alpha_comp_SAMAN_V001.mov").write_text("x", encoding="utf-8")
        plan_dir = (tmp_path / "HTLR" / "COMP" / "EP_07"
                    / "plan_alpha_comp_SAMAN_V001")
        plan_dir.mkdir(parents=True)
        (plan_dir / "plan_alpha_comp_SAMAN_v001.nk").write_text(
            "x", encoding="utf-8"
        )
    plano = "HTLR/COMP/EP_07/plan_alpha_comp_SAMAN_V001"
    pr = {
        "root_fps": 24.0,
        "root_first": 1,
        "root_last": 1665,
        "root_w": 1920,
        "root_h": 1080,
        "plate_first": 1001,
        "plate_last": 2665,
        "nodes": {
            "DELIVERY_EXR": {
                "first": 1001,
                "last": 2665,
                "file": "/b/HTLR/FROM_VFX/EP_07/20260628/DELIVERY_EXR/"
                        "plan_alpha_comp_SAMAN_V001.####.exr",
                "file_type": "exr",
            },
            "REVIEW_REC709": {
                "first": 1001,
                "last": 2558,  # 1558 frames: drift vs plate 1665
                "file": "/b/HTLR/FROM_VFX/EP_07/20260628/REVIEW_REC709/"
                        "plan_alpha_comp_SAMAN_V001.mov",
                "file_type": "mov",
            },
        },
    }
    return plano, "plan_alpha_comp_SAMAN_v001.nk", pr


def _plate_ffprobe_fixture():
    """Plate 23.976 / 2048x1156 / 1665 (difiere del root 24fps 1920x1080)."""
    return {
        "ruta": "HTLR/TO_VFX/EP_07/20260628/plan_alpha_comp_SAMAN_V001.mov",
        "codec": "prores",
        "bit_depth": 12,
        "colorspace": "bt709",
        "width": 2048,
        "height": 1156,
        "fps": 23.976023976,
        "frames": 1665,
        "duration": 69.444375,
        "r_frame_rate": "24000/1001",
    }


def test_es_flujo_asistido_con_cada_flag_qc():
    """Cada flag nuevo del gate activa el flujo asistido (RC-QC-04)."""
    assert orquestador.es_flujo_asistido(_args_qc(force_qc=True)) is True
    assert orquestador.es_flujo_asistido(_args_qc(plate_date="20260628-2")) is True
    assert orquestador.es_flujo_asistido(_args_qc(validar_solo_duracion=True)) is True
    assert orquestador.es_flujo_asistido(_args_qc(fps_forzar="23.976")) is True


def test_es_flujo_asistido_legacy_sin_flags_qc():
    """Legacy --comp sin flags nuevos (ni QC) => False: sin gate (RC-QC-04)."""
    args = argparse.Namespace(
        proyecto=None, comp_dir=None, resolve_latest=False, use_version=None,
        force_qc=False, plate_date=None, validar_solo_duracion=False,
        fps_forzar=None,
    )
    assert orquestador.es_flujo_asistido(args) is False


def test_gate_habilitado_solo_flujo_asistido_con_probe():
    """Gate en secuencia PROBE->QC: asistido + probe con nodes, y legacy no."""
    pr = {"nodes": {"DELIVERY_EXR": {}}, "root_fps": 24.0}
    legacy = argparse.Namespace(
        proyecto=None, comp_dir=None, resolve_latest=False, use_version=None,
        force_qc=False, plate_date=None, validar_solo_duracion=False,
        fps_forzar=None,
    )

    assert orquestador.gate_habilitado(legacy, pr) is False
    assert orquestador.gate_habilitado(_args_qc(), pr) is True
    assert orquestador.gate_habilitado(_args_qc(), None) is False


def test_gate_qc_con_force_escribe_reporte_y_devuelve_qc_set(
    tmp_path, monkeypatch, capsys
):
    """--force-qc: reporte JSON en TEST_RENDER + discrepancias + QC_SET (D3/D6)."""
    monkeypatch.setattr(layouts.platform, "system", lambda: "Darwin")
    plano, version, pr = _plano_fixture(tmp_path)
    monkeypatch.setattr(
        orquestador.plate_qc, "probar_plate", lambda ruta: _plate_ffprobe_fixture()
    )

    payload, discrepancias, qc_set = orquestador.gate_qc(
        _args_qc(force_qc=True), _config_qc(tmp_path),
        layouts.LAYOUTS["HTLR"], plano, version, pr,
    )

    assert payload["proyecto"] == "HTLR"
    tipos = {d["tipo"] for d in discrepancias}
    assert "fps" in tipos and "resolucion" in tipos
    assert any(d["severidad"] == "warning" and d["nodo"] == "REVIEW_REC709"
               for d in discrepancias)
    assert qc_set["DELIVERY_EXR"]["format"] == "2048x1156"
    assert qc_set["DELIVERY_EXR"]["fps"] == 23.976
    # reporte en TEST_RENDER (relativo a la base) + resumen stdout
    reportes = list((tmp_path / "TEST_RENDER").glob("qc_HTLR_*.json"))
    assert len(reportes) == 1
    assert "REPORTE QC" in capsys.readouterr().out


def test_gate_qc_sin_force_aborta_exit_3_en_auto(tmp_path, monkeypatch, capsys):
    """Discrepancia bloqueante sin --force-qc => exit 3 (decisión al agente)."""
    monkeypatch.setattr(layouts.platform, "system", lambda: "Darwin")
    plano, version, pr = _plano_fixture(tmp_path)
    monkeypatch.setattr(
        orquestador.plate_qc, "probar_plate", lambda ruta: _plate_ffprobe_fixture()
    )

    def decision_auto(dec_id, problema, opciones, default):
        # modo auto (D5): el bloque __DECISION__ sale por stdout, sin TTY
        print("__DECISION__" + json.dumps({"id": dec_id, "problema": problema,
                                           "opciones": opciones,
                                           "default": default}))
        return None

    monkeypatch.setattr(orquestador.plate_qc, "decision", decision_auto)

    with pytest.raises(SystemExit) as exc:
        orquestador.gate_qc(
            _args_qc(), _config_qc(tmp_path),
            layouts.LAYOUTS["HTLR"], plano, version, pr,
        )

    assert exc.value.code == 3
    assert "__DECISION__" in capsys.readouterr().out


def test_gate_qc_fps_forzar_resuelve_y_qc_set_con_fps_forzado(
    tmp_path, monkeypatch, capsys
):
    """--fps-forzar 24.0: procede y QC_SET lleva el fps forzado (override D5)."""
    monkeypatch.setattr(layouts.platform, "system", lambda: "Darwin")
    plano, version, pr = _plano_fixture(tmp_path)
    plate = _plate_ffprobe_fixture()
    plate["width"], plate["height"] = 1920, 1080  # solo difiere el fps
    monkeypatch.setattr(orquestador.plate_qc, "probar_plate", lambda ruta: plate)

    payload, discrepancias, qc_set = orquestador.gate_qc(
        _args_qc(fps_forzar="24.0"), _config_qc(tmp_path),
        layouts.LAYOUTS["HTLR"], plano, version, pr,
    )

    assert qc_set["DELIVERY_EXR"]["fps"] == 24.0
    assert payload["proyecto"] == "HTLR"  # el reporte existe igual
    assert any(d["tipo"] == "fps" for d in discrepancias)


def test_gate_qc_probe_fallo_aborta_nombrando_la_ruta(tmp_path, monkeypatch):
    """Probe fallido => abort nombrando la ruta del plate (RC-QC-02)."""
    monkeypatch.setattr(layouts.platform, "system", lambda: "Darwin")
    plano, version, pr = _plano_fixture(tmp_path)

    def falla(ruta):
        raise plate_qc.ProbeError(ruta, "No such file")

    monkeypatch.setattr(orquestador.plate_qc, "probar_plate", falla)

    with pytest.raises(SystemExit) as exc:
        orquestador.gate_qc(
            _args_qc(), _config_qc(tmp_path),
            layouts.LAYOUTS["HTLR"], plano, version, pr,
        )

    assert "plan_alpha_comp_SAMAN_V001.mov" in str(exc.value.code)


def test_env_worker_lleva_qc_set_solo_en_render_con_quoting():
    """QC_SET viaja en render (no en probe) con el JSON intacto (D6)."""
    spec = {"DELIVERY_EXR": {"fps": 23.976, "format": "2048x1156"}}
    args = argparse.Namespace(
        comp="x.nk", wnode="DELIVERY_EXR", wnodes=None, piggyback=None,
        force_exr=False, qc_set=json.dumps(spec),
        to_suf=None, comp_suf=None, from_suf=None,
    )
    env_render = orquestador.env_worker({"base": "/b"}, args, "render")
    env_probe = orquestador.env_worker({"base": "/b"}, args, "probe")

    assert json.loads(env_render["QC_SET"]) == spec
    assert "QC_SET" not in env_probe


def test_ejecutar_remoto_quoting_qc_set_json_intacto(monkeypatch):
    """env KEY='val' con QC_SET JSON integro en el argv remoto (threat env)."""
    llamadas = []

    def fake_run(cmd, **kw):
        llamadas.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(orquestador.subprocess, "run", fake_run)
    worker = {
        "nombre": "vfxserver",
        "ssh": "render_user" + "@" + "vfxserver.studio.local",
        "bin": "/opt/Nuke18.0v1/Nuke18.0",
        "base": "/media/wupm/2026",
        "lc_all": True,
    }
    env = {"QC_SET": '{"DELIVERY_EXR":{"fps":23.976,"format":"2048x1156"}}'}

    orquestador.ejecutar(
        worker, ["/opt/Nuke18.0v1/Nuke18.0", "-t", "render_worker.py"], env, timeout=30
    )

    token_env = next(t for t in llamadas[0][0] if t.startswith("env "))
    assert "QC_SET='{\"DELIVERY_EXR\":{\"fps\":23.976,\"format\":\"2048x1156\"}}'" in token_env
    assert not llamadas[0][1].get("shell")


# ---------------------------------------------------------------------------
# Guard de fuente: sin datos del estudio en el codigo
# ---------------------------------------------------------------------------


def test_orquestador_sin_datos_reales_del_estudio():
    """El codigo no contiene IPs, usuarios, bases ni sufijos del estudio."""
    fuente = RUTA_ORQUESTADOR.read_text(encoding="utf-8")
    octetos_ip = "192" + "." + "168"
    assert octetos_ip not in fuente
    assert "servermac" not in fuente
    assert "BASE_MAC" not in fuente
    assert "BASE_LINUX" not in fuente
    assert "/HTLR/" not in fuente
    # Ningun par usuario-host literal (la composicion ssh es dinamica, sin datos).
    assert re.search(r"@[a-z]", fuente) is None