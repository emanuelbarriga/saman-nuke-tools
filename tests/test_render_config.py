"""Tests de render_distribuido.render_config (carga estricta, sin Nuke).

Cubren la cadena de resolucion (env RENDER_CONFIG_BASE / entorno -> JSON del
disco -> RENDER_LOCAL_CONFIG), la politica estricta (FileNotFoundError ->
sugerir plantilla; OSError/gate -> fallo de montaje sin plantilla), la
autonomia del local completo sin disco, el validador acumulativo de esquema
y el gate de montaje cache-free (D7). Usan tmp_path + monkeypatch: nunca
tocan el storage real.
"""

import builtins
import json
import subprocess
import sys

import pytest

from render_distribuido import render_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def config_valida():
    """Dict conforme al esquema, sin datos reales (hostnames, sin IPs)."""
    return {
        "bases_por_so": {
            "macOS": "/Volumes/wupm/2026",
            "Windows": "W:\\wupm\\2026",
            "Linux": "/mnt/wupm/2026",
        },
        "workers": [
            {
                "nombre": "imac",
                "ssh": None,
                "ssh_user": "artista",
                "nuke_exec": "/Applications/Nuke17.1v1/Nuke17.1v1.app/Contents/MacOS/Nuke17.1",
                "base": "/Volumes/wupm/2026",
                "lc_all": False,
            },
            {
                "nombre": "vfxserver",
                "ssh": "vfxserver.studio.local",
                "ssh_user": "admin_render",
                "nuke_exec": "/opt/Nuke17.1v1/Nuke17.1/Nuke17.1",
                "base": "/mnt/wupm/2026",
                "lc_all": True,
            },
        ],
        "sufijos": {
            "TO_VFX": "/HTLR/TO_VFX/",
            "COMP": "/HTLR/COMP/",
            "FROM_VFX": "/HTLR/FROM_VFX/",
        },
    }


class EntornoFake:
    """Fake de SamanTools.entorno con base controlable."""

    def __init__(self, base=None):
        self.base = base

    def primera_ruta_disponible(self, so):
        return self.base

    def detectar_so(self):
        return "macOS"


def escribir_json(tmp_path, cfg):
    """Escribe {tmp_path}/.saman/studio_config.json con cfg."""
    destino = tmp_path / ".saman" / "studio_config.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(cfg), encoding="utf-8")
    return destino


@pytest.fixture
def sin_env_base(monkeypatch):
    """Garantiza que RENDER_CONFIG_BASE no venga heredado del entorno."""
    monkeypatch.delenv(render_config.ENV_BASE, raising=False)


@pytest.fixture
def entorno_vacio(monkeypatch):
    """entorno fake sin base (nada montado)."""
    fake = EntornoFake(base=None)
    monkeypatch.setattr(render_config, "_cargar_entorno", lambda: fake)
    return fake


# ---------------------------------------------------------------------------
# Cadena de resolucion
# ---------------------------------------------------------------------------


def test_happy_path_json_local_merge_por_llave(tmp_path, monkeypatch, sin_env_base):
    """Local sobreescribe por llave al JSON central (merge per-key)."""
    # disk: sufijos COMP/FROM_VFX distintos y base Linux original
    cfg_disco = config_valida()
    cfg_disco["sufijos"]["COMP"] = "/DISCO/COMP/"
    cfg_disco["sufijos"]["FROM_VFX"] = "/DISCO/FROM_VFX/"
    escribir_json(tmp_path, cfg_disco)
    # local: solo sobreescribe TO_VFX y la base Linux
    local = {
        "sufijos": {"TO_VFX": "/LOCAL/TO/"},
        "bases_por_so": {"Linux": "/mnt/otra_base"},
    }
    monkeypatch.setenv(render_config.ENV_BASE, str(tmp_path))
    monkeypatch.setattr(render_config, "_cargar_config_local", lambda: local)

    efectiva = render_config.obtener_config_efectiva()

    assert efectiva["sufijos"]["TO_VFX"] == "/LOCAL/TO/"
    assert efectiva["sufijos"]["COMP"] == "/DISCO/COMP/"
    assert efectiva["sufijos"]["FROM_VFX"] == "/DISCO/FROM_VFX/"
    assert efectiva["bases_por_so"]["Linux"] == "/mnt/otra_base"
    assert efectiva["bases_por_so"]["macOS"] == "/Volumes/wupm/2026"
    assert [w["nombre"] for w in efectiva["workers"]] == ["imac", "vfxserver"]


def test_base_env_gana_a_entorno(tmp_path, monkeypatch, sin_env_base):
    """RENDER_CONFIG_BASE gana a entorno.primera_ruta_disponible()."""
    base_env = tmp_path / "base_env"
    base_env.mkdir()
    escribir_json(base_env, config_valida())

    base_entorno = tmp_path / "base_entorno"
    base_entorno.mkdir()
    fake = EntornoFake(base=str(base_entorno))
    monkeypatch.setattr(render_config, "_cargar_entorno", lambda: fake)
    monkeypatch.setattr(render_config, "_cargar_config_local", lambda: None)
    monkeypatch.setenv(render_config.ENV_BASE, str(base_env))

    efectiva = render_config.obtener_config_efectiva()

    assert efectiva["workers"][0]["nombre"] == "imac"
    # el JSON de base_env fue el que se leyo (el de base_entorno no existe)
    assert not (base_entorno / ".saman" / "studio_config.json").exists()


def test_local_completo_sin_base_ni_disco_funciona(monkeypatch, entorno_vacio):
    """Autonomia: local completo sin base ni archivo en disco -> funciona."""
    local = config_valida()
    local["sufijos"]["TO_VFX"] = "/SOLO_LOCAL/TO/"
    monkeypatch.setattr(render_config, "_cargar_config_local", lambda: local)

    efectiva = render_config.obtener_config_efectiva()

    assert efectiva["sufijos"]["TO_VFX"] == "/SOLO_LOCAL/TO/"
    assert len(efectiva["workers"]) == 2


def test_local_completo_con_archivo_ausente_funciona(tmp_path, monkeypatch, sin_env_base):
    """Autonomia: archivo ausente + local completo -> usa local, sin abort."""
    monkeypatch.setenv(render_config.ENV_BASE, str(tmp_path))
    local = config_valida()
    monkeypatch.setattr(render_config, "_cargar_config_local", lambda: local)

    efectiva = render_config.obtener_config_efectiva()

    assert efectiva["workers"][0]["nombre"] == "imac"
    assert efectiva["bases_por_so"]["macOS"] == "/Volumes/wupm/2026"


def test_local_incompleto_sin_disco_aborta_con_diagnostico(tmp_path, monkeypatch, sin_env_base):
    """Local incompleto + archivo ausente -> SystemExit con llaves faltantes."""
    monkeypatch.setenv(render_config.ENV_BASE, str(tmp_path))
    local = config_valida()
    del local["sufijos"]
    local["workers"][1].pop("nuke_exec")
    monkeypatch.setattr(render_config, "_cargar_config_local", lambda: local)

    with pytest.raises(SystemExit) as exc:
        render_config.obtener_config_efectiva()

    mensaje = str(exc.value.code)
    assert "sufijos" in mensaje
    assert "workers[1].nuke_exec" in mensaje


# ---------------------------------------------------------------------------
# Politica estricta
# ---------------------------------------------------------------------------


def test_archivo_faltante_sugiere_copiar_plantilla(tmp_path, monkeypatch, sin_env_base):
    """FileNotFoundError -> mensaje 'config missing' + sugerir plantilla."""
    monkeypatch.setenv(render_config.ENV_BASE, str(tmp_path))
    monkeypatch.setattr(render_config, "_cargar_config_local", lambda: None)

    with pytest.raises(SystemExit) as exc:
        render_config.obtener_config_efectiva()

    mensaje = str(exc.value.code)
    assert "Config de render faltante" in mensaje
    assert ".saman/studio_config.json" in mensaje
    assert "studio_config.example.json" in mensaje


def test_archivo_faltante_con_unidad_conectada_sugiere_plantilla(tmp_path, monkeypatch, sin_env_base):
    """Gate OK (unidad responde) + archivo ausente -> sugerir plantilla."""
    fake = EntornoFake(base=str(tmp_path))
    monkeypatch.setattr(render_config, "_cargar_entorno", lambda: fake)
    monkeypatch.setattr(render_config, "_cargar_config_local", lambda: None)

    with pytest.raises(SystemExit) as exc:
        render_config.obtener_config_efectiva()

    mensaje = str(exc.value.code)
    assert "studio_config.example.json" in mensaje
    assert "Config de render faltante" in mensaje


def test_json_invalido_sugiere_copiar_plantilla(tmp_path, monkeypatch, sin_env_base):
    """JSON corrupto en disco -> tratar como config ausente/invalida + plantilla."""
    destino = tmp_path / ".saman" / "studio_config.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("{ esto no es json", encoding="utf-8")
    monkeypatch.setenv(render_config.ENV_BASE, str(tmp_path))
    monkeypatch.setattr(render_config, "_cargar_config_local", lambda: None)

    with pytest.raises(SystemExit) as exc:
        render_config.obtener_config_efectiva()

    mensaje = str(exc.value.code)
    assert "inválida" in mensaje
    assert "studio_config.example.json" in mensaje


def test_json_no_dict_invalido_sugiere_plantilla(tmp_path, monkeypatch, sin_env_base):
    """JSON valido pero con forma de lista -> invalido, se sugiere plantilla."""
    escribir_json(tmp_path, [1, 2, 3])
    monkeypatch.setenv(render_config.ENV_BASE, str(tmp_path))
    monkeypatch.setattr(render_config, "_cargar_config_local", lambda: None)

    with pytest.raises(SystemExit) as exc:
        render_config.obtener_config_efectiva()

    mensaje = str(exc.value.code)
    assert "inválida" in mensaje
    assert "studio_config.example.json" in mensaje


def test_gate_fallido_mensaje_de_montaje_sin_plantilla(tmp_path, monkeypatch, sin_env_base):
    """Gate de montaje caido -> fallo de conexion/montaje, NUNCA plantilla."""
    fake = EntornoFake(base=str(tmp_path))
    monkeypatch.setattr(render_config, "_cargar_entorno", lambda: fake)

    llamadas = []

    def gate_caido(base, timeout=3, intentos=2):
        llamadas.append((base, timeout, intentos))
        return False

    monkeypatch.setattr(render_config, "_gate_mount", gate_caido)
    monkeypatch.setattr(render_config, "_cargar_config_local", lambda: None)

    with pytest.raises(SystemExit) as exc:
        render_config.obtener_config_efectiva()

    mensaje = str(exc.value.code)
    assert llamadas == [(str(tmp_path), 3, 2)]
    assert "montaje" in mensaje
    assert "studio_config.example.json" not in mensaje


def test_oserror_al_abrir_mensaje_de_montaje_sin_plantilla(tmp_path, monkeypatch, sin_env_base):
    """OSError/EIO al abrir el JSON -> fallo de conexion/montaje, sin plantilla."""
    escribir_json(tmp_path, config_valida())
    monkeypatch.setenv(render_config.ENV_BASE, str(tmp_path))
    monkeypatch.setattr(render_config, "_cargar_config_local", lambda: None)

    real_open = builtins.open

    def open_con_eio(path, *args, **kwargs):
        if str(path).endswith("studio_config.json"):
            raise OSError(5, "EIO: input/output error")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", open_con_eio)

    with pytest.raises(SystemExit) as exc:
        render_config.obtener_config_efectiva()

    mensaje = str(exc.value.code)
    assert "conex" in mensaje  # conexión o conexion
    assert "studio_config.example.json" not in mensaje


def test_sin_base_ni_local_sugiere_copiar_plantilla(monkeypatch, entorno_vacio):
    """Escenario 'No config available': sin base ni local -> plantilla."""
    monkeypatch.setattr(render_config, "_cargar_config_local", lambda: None)

    with pytest.raises(SystemExit) as exc:
        render_config.obtener_config_efectiva()

    mensaje = str(exc.value.code)
    assert "Config de render faltante" in mensaje
    assert "studio_config.example.json" in mensaje


def test_local_completo_rescata_mount_caido(tmp_path, monkeypatch, sin_env_base):
    """Spec: disco caido por red + local completo -> usa local, sin abort."""
    fake = EntornoFake(base=str(tmp_path))
    monkeypatch.setattr(render_config, "_cargar_entorno", lambda: fake)
    monkeypatch.setattr(render_config, "_gate_mount", lambda base, timeout=3, intentos=2: False)
    local = config_valida()
    local["sufijos"]["TO_VFX"] = "/AUN_ASIN_MOUNT/TO/"
    monkeypatch.setattr(render_config, "_cargar_config_local", lambda: local)

    efectiva = render_config.obtener_config_efectiva()

    assert efectiva["sufijos"]["TO_VFX"] == "/AUN_ASIN_MOUNT/TO/"
    assert len(efectiva["workers"]) == 2


# ---------------------------------------------------------------------------
# Validador de esquema (puro)
# ---------------------------------------------------------------------------


def test_validar_esquema_ok_devuelve_vacio():
    """Config completa y bien tipada -> sin errores."""
    assert render_config.validar_esquema(config_valida()) == []


def test_validar_esquema_acumula_todas_las_faltantes():
    """Faltantes multiples (1er nivel + worker) acumuladas con key path."""
    cfg = config_valida()
    del cfg["sufijos"]
    cfg["workers"][0].pop("lc_all")
    cfg["workers"][1].pop("ssh_user")

    errores = render_config.validar_esquema(cfg)

    assert len(errores) >= 3
    alguno = "\n".join(errores)
    assert "sufijos" in alguno
    assert "workers[0].lc_all" in alguno
    assert "workers[1].ssh_user" in alguno


def test_obtener_efectiva_un_systemexit_con_todas_las_faltantes(tmp_path, monkeypatch, sin_env_base):
    """Escenario spec: un solo SystemExit lista TODAS las faltantes."""
    cfg = config_valida()
    del cfg["sufijos"]
    cfg["workers"][0].pop("nuke_exec")
    escribir_json(tmp_path, cfg)
    monkeypatch.setenv(render_config.ENV_BASE, str(tmp_path))
    monkeypatch.setattr(render_config, "_cargar_config_local", lambda: None)

    with pytest.raises(SystemExit) as exc:
        render_config.obtener_config_efectiva()

    mensaje = str(exc.value.code)
    assert "sufijos" in mensaje
    assert "workers[0].nuke_exec" in mensaje


def test_tipo_incorrecto_bases_por_so_lista():
    """bases_por_so como lista -> error que indica el tipo esperado."""
    cfg = config_valida()
    cfg["bases_por_so"] = ["/Volumes/wupm/2026"]

    errores = render_config.validar_esquema(cfg)

    alguno = "\n".join(errores)
    assert "bases_por_so" in alguno
    assert "dict" in alguno


def test_tipo_incorrecto_lc_all_str_y_sufijos_lista():
    """lc_all como string y sufijos como lista -> errores de tipo claros."""
    cfg = config_valida()
    cfg["workers"][0]["lc_all"] = "si"
    cfg["sufijos"] = ["/TO/"]

    errores = render_config.validar_esquema(cfg)

    alguno = "\n".join(errores)
    assert "workers[0].lc_all" in alguno
    assert "bool" in alguno
    assert "sufijos" in alguno
    assert "dict" in alguno


def test_ssh_none_local_es_valido():
    """worker local (ssh None) pasa la validacion."""
    cfg = config_valida()
    cfg["workers"][0]["ssh"] = None

    assert render_config.validar_esquema(cfg) == []


def test_ssh_tipo_incorrecto_int():
    """ssh numerico -> error de tipo."""
    cfg = config_valida()
    cfg["workers"][0]["ssh"] = 192

    errores = render_config.validar_esquema(cfg)

    alguno = "\n".join(errores)
    assert "workers[0].ssh" in alguno
    assert "str" in alguno


def test_workers_no_lista_y_entry_no_dict():
    """workers que no es lista y entrada que no es dict -> errores de tipo."""
    cfg = config_valida()
    cfg["workers"] = "imac"
    errores = render_config.validar_esquema(cfg)
    assert any("workers" in e and "list" in e for e in errores)

    cfg2 = config_valida()
    cfg2["workers"] = ["imac"]
    errores2 = render_config.validar_esquema(cfg2)
    assert any("workers[0]" in e and "dict" in e for e in errores2)


def test_ssh_valido_de_worker_se_valida_completo():
    """ssh de worker como hostname valido (str) no genera error."""
    cfg = config_valida()
    cfg["workers"][1]["ssh"] = "vfxserver.studio.local"

    assert render_config.validar_esquema(cfg) == []


# ---------------------------------------------------------------------------
# Gate de montaje (D7)
# ---------------------------------------------------------------------------


def test_gate_mount_ok_con_directorio_real(tmp_path):
    """Base existente y respondiendo -> gate True (ls -d, sin cache)."""
    assert render_config._gate_mount(str(tmp_path), timeout=3, intentos=2) is True


def test_gate_mount_reintenta_y_gana_en_segundo_intento(tmp_path, monkeypatch):
    """Primer intento timeout, segundo OK -> True y hubo 2 intentos."""
    intentos = []

    def fake_run(cmd, **kw):
        intentos.append(kw.get("timeout"))
        if len(intentos) == 1:
            raise subprocess.TimeoutExpired(cmd, timeout=kw.get("timeout", 3))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(render_config.subprocess, "run", fake_run)

    assert render_config._gate_mount(str(tmp_path), timeout=3, intentos=2) is True
    assert intentos == [3, 3]


def test_gate_mount_ambos_intentos_fallan_devuelve_falso(tmp_path, monkeypatch):
    """Dos timeouts seguidos -> gate False (montaje caido), 2 intentos."""
    intentos = []

    def fake_run(cmd, **kw):
        intentos.append(kw.get("timeout"))
        raise subprocess.TimeoutExpired(cmd, timeout=kw.get("timeout", 3))

    monkeypatch.setattr(render_config.subprocess, "run", fake_run)

    assert render_config._gate_mount(str(tmp_path), timeout=3, intentos=2) is False
    assert intentos == [3, 3]


# ---------------------------------------------------------------------------
# Contrato de exportacion
# ---------------------------------------------------------------------------


def test_constantes_publicas():
    """Constantes de contrato del design (Interfaces/Contracts)."""
    assert render_config.ENV_BASE == "RENDER_CONFIG_BASE"
    assert render_config.ARCHIVO_DISCO == ".saman/studio_config.json"