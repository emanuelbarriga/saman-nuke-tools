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
import platform
import re
from pathlib import Path

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