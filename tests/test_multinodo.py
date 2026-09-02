"""Tests del flujo multi-nodo (PR2, D4): descubrimiento real de Write nodes,
politica de existencia EXR/MOV, CALIB/PLAN solo entrega EXR, piggyback con
use_limit y --force-exr.

Cubren RC-MN-01/02/03:

- Descubrimiento de Write reales por nombre (DELIVERY_EXR/DELIVERY_DWG/
  REVIEW_REC709/SBS_REC709) y filtro ``--wnodes``; cero labels friendly
  ("delivery"/"preview"/"side by side") como nombres de nodo.
- Politica de existencia por tipo: EXR por frame (765 faltantes de 1665),
  MOV por archivo; un .mov con digitos en el nombre NO es secuencia EXR.
- CALIB/PLAN solo sobre DELIVERY_EXR; previews piggyback con rangos propios
  (use_limit) y ``--force-exr`` conservando duracion y resolucion.

Sin Nuke real: el worker se importa con el stub de conftest (MODE=render) y
nuke.toNode se reemplaza por fakes hermeticos por test. Las rutas son
ficticias (tmp_path).
"""

import importlib
import os
import sys

import nuke
import pytest

from render_distribuido import render_distribuido as orquestador

MODULO_WORKER = "render_distribuido.render_worker"


# ---------------------------------------------------------------------------
# Fixture: worker con el stub de conftest (mismo patron que test_render_worker)
# ---------------------------------------------------------------------------


@pytest.fixture
def worker(monkeypatch):
    """Importa render_worker con env controlado y stub minimo (MODE=render)."""
    monkeypatch.setattr(nuke, "scriptOpen", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(nuke, "execute", lambda *a, **k: None, raising=False)
    monkeypatch.setenv("BASE", "/Volumes/wupm/2026")
    monkeypatch.setenv("MODE", "render")
    sys.modules.pop(MODULO_WORKER, None)
    yield importlib.import_module(MODULO_WORKER)
    sys.modules.pop(MODULO_WORKER, None)


class _Knob:
    """Knob minimo: value()/setValue() (y getEvaluatedValue para 'file')."""

    def __init__(self, valor):
        self.valor = valor

    def value(self):
        return self.valor

    def setValue(self, v):
        self.valor = v

    def getEvaluatedValue(self):
        return self.valor


class _WriteFake:
    """Write fake para el worker: knobs first/last/use_limit/file/file_type.

    Los knobs con valor None se omiten (simula un nodo sin ese knob).
    """

    def __init__(self, file, file_type="exr", first=1, last=90, use_limit=False):
        knobs = {
            "file": _Knob(file),
            "first": _Knob(first),
            "last": _Knob(last),
            "use_limit": _Knob(use_limit),
        }
        if file_type is not None:
            knobs["file_type"] = _Knob(file_type)
        self.knobs_d = knobs

    def knobs(self):
        return set(self.knobs_d)

    def __getitem__(self, k):
        return self.knobs_d[k]


def toNode_fake(mapping):
    """nuke.toNode que devuelve el fake de la tabla, o None."""
    return lambda nombre: mapping.get(nombre)


# ---------------------------------------------------------------------------
# RC-MN-01: descubrimiento por nombre real (worker) + filtro --wnodes
# ---------------------------------------------------------------------------


def test_scan_write_nodes_descubre_solo_nombres_reales(worker, monkeypatch):
    """Comp con DELIVERY_EXR/REVIEW_REC709/SBS_REC709 => exactamente esos (RC-MN-01)."""
    fakes = {
        "DELIVERY_EXR": _WriteFake(file="/b/ENTREGAS/deli.####.exr"),
        "REVIEW_REC709": _WriteFake(file="/b/ENTREGAS/review.mov", file_type="mov"),
        "SBS_REC709": _WriteFake(file="/b/ENTREGAS/sbs.mov", file_type="mov"),
    }
    monkeypatch.setattr(nuke, "toNode", toNode_fake(fakes), raising=False)

    descubiertos = worker.scan_write_nodes()

    assert sorted(descubiertos) == ["DELIVERY_EXR", "REVIEW_REC709", "SBS_REC709"]
    # DELIVERY_DWG ausente del comp => no se descubre
    assert "DELIVERY_DWG" not in descubiertos


def test_info_nodo_expone_first_last_use_limit_file_tipo(worker, monkeypatch):
    """El payload por nodo expone first/last/use_limit/file/file_type (D4/D6)."""
    fake = _WriteFake(
        file="/base/FROM_VFX/EP_07/deli.1001.exr",
        file_type="exr",
        first=1001,
        last=1665,
        use_limit=False,
    )
    monkeypatch.setattr(nuke, "toNode", toNode_fake({"DELIVERY_EXR": fake}), raising=False)

    info = worker.info_nodo("DELIVERY_EXR", fake)

    assert info == {
        "first": 1001,
        "last": 1665,
        "use_limit": False,
        "file": "/base/FROM_VFX/EP_07/deli.1001.exr",
        "file_type": "exr",
    }


def test_file_type_de_knob_y_fallback_por_extension(worker):
    """file_type del knob gana; sin knob cae a la extension del file."""
    assert worker.file_type_de(_WriteFake(file="/x/a.mov", file_type="mov")) == "mov"
    # sin knob file_type => extension
    assert worker.file_type_de(_WriteFake(file="/x/a.mov", file_type=None)) == "mov"
    assert worker.file_type_de(_WriteFake(file="/x/a.1001.exr", file_type=None)) == "exr"


def test_filtrar_wnodes_default_solo_rol_entrega():
    """Sin --wnodes: todos los descubiertos con rol de entrega (DELIVERY_*)."""
    descubiertos = {
        "DELIVERY_EXR": {},
        "DELIVERY_DWG": {},
        "REVIEW_REC709": {},
        "SBS_REC709": {},
    }
    assert orquestador.filtrar_wnodes(descubiertos, None) == [
        "DELIVERY_EXR", "DELIVERY_DWG",
    ]
    # comp sin DELIVERY_DWG (escenario RC-MN-01 exacto)
    parcial = {"DELIVERY_EXR": {}, "REVIEW_REC709": {}, "SBS_REC709": {}}
    assert orquestador.filtrar_wnodes(parcial, None) == ["DELIVERY_EXR"]


def test_filtrar_wnodes_explicito_selecciona_subset():
    """--wnodes DELIVERY_EXR,SBS_REC709 => solo esos (filtra los demas)."""
    descubiertos = {
        "DELIVERY_EXR": {},
        "REVIEW_REC709": {},
        "SBS_REC709": {},
    }
    assert orquestador.filtrar_wnodes(descubiertos, "DELIVERY_EXR,SBS_REC709") == [
        "DELIVERY_EXR", "SBS_REC709",
    ]


def test_filtrar_wnodes_descarta_no_descubiertos_y_metacaracteres():
    """Nombres ajenos al discovery (incluso con metacaracteres) jamas pasan.

    El pedido se compara por coincidencia exacta contra lo descubierto: un
    nombre con metacaracteres no es un nombre real de nodo.
    """
    descubiertos = {"DELIVERY_EXR": {}}

    assert orquestador.filtrar_wnodes(
        descubiertos, "DELIVERY_EXR;touch /tmp/x,REVIEW_REC709"
    ) == []

    # invariante: el resultado siempre es subconjunto de lo descubierto
    for pedido in ("DELIVERY_EXR", "DELIVERY_EXR;touch /tmp/x", "REVIEW_REC709"):
        resultado = orquestador.filtrar_wnodes(descubiertos, pedido)
        assert set(resultado) <= set(descubiertos)


def test_nombres_reales_sin_labels_friendly():
    """RC-MN-01: cero 'delivery'/'preview'/'side by side' como nombres de nodo.

    El mapping queda en los nombres reales DELIVERY_*/REVIEW_REC709/SBS_*.
    """
    assert orquestador.NODOS_RENDER == (
        "DELIVERY_EXR", "DELIVERY_DWG", "REVIEW_REC709", "SBS_REC709",
    )
    for nombre in orquestador.NODOS_RENDER:
        assert "delivery" not in nombre
        assert "preview" not in nombre
        assert "side by side" not in nombre
    assert orquestador.NODOS_ENTREGA == ("DELIVERY_EXR", "DELIVERY_DWG")
    assert orquestador.NODOS_PREVIEW == ("REVIEW_REC709", "SBS_REC709")


# ---------------------------------------------------------------------------
# D3: worker mode qc_set — reescribe el nodo delivery a las specs del plate
# (Regla de Oro: el Write de Nuke no se confia ciegamente). Knobs reales:
# fps del root, format y first/last del Write (check manual en worker real).
# ---------------------------------------------------------------------------


class _KnobQc:
    """Knob minimo con value/setValue para los fakes de qc_set."""

    def __init__(self, valor):
        self.valor = valor

    def value(self):
        return self.valor

    def setValue(self, v):
        self.valor = v


class _WriteQcFake:
    """Write con knobs format/first/last (qc_set no toca file/file_type)."""

    def __init__(self, format="1920x1080", first=1, last=1558):
        self.knobs_d = {
            "format": _KnobQc(format),
            "first": _KnobQc(first),
            "last": _KnobQc(last),
        }

    def knobs(self):
        return set(self.knobs_d)

    def __getitem__(self, k):
        return self.knobs_d[k]


class _RootQcFake:
    """Root con knob fps (el fps en Nuke es global al root)."""

    def __init__(self, fps=24.0):
        self.knobs_d = {"fps": _KnobQc(fps)}

    def __getitem__(self, k):
        return self.knobs_d[k]


def _root_fake(fps=24.0):
    return lambda: _RootQcFake(fps)


def test_aplicar_qc_spec_reescribe_format_fps_y_rango(worker):
    """QC_SET aplica fps (root), format y first/last (Write) al delivery (D3)."""
    nodo = _WriteQcFake("1920x1080", first=1, last=1558)
    spec = {"DELIVERY_EXR": {"fps": 23.976, "format": "2048x1156",
                             "first": 1001, "last": 2665}}

    aplicado = worker.aplicar_qc_spec(spec, toNode=lambda n: nodo,
                                      root=_root_fake(24.0))

    assert nodo["format"].value() == "2048x1156"
    assert nodo["first"].value() == 1001
    assert nodo["last"].value() == 2665
    assert aplicado["DELIVERY_EXR"]["format"] == "2048x1156"
    assert aplicado["DELIVERY_EXR"]["fps"] == 23.976
    # fps del plate se aplica al root, no al Write
    assert "fps" in aplicado["DELIVERY_EXR"]


def test_aplicar_qc_spec_reescribe_fps_en_el_root(worker):
    """El fps viaja al knob fps del root (Nuke: frame rate global)."""
    root = _RootQcFake(24.0)
    nodo = _WriteQcFake()
    spec = {"DELIVERY_EXR": {"fps": 23.976, "format": "2048x1156"}}

    worker.aplicar_qc_spec(spec, toNode=lambda n: nodo, root=lambda: root)

    assert root["fps"].value() == 23.976


def test_aplicar_qc_spec_nodo_ausente_se_marca_sin_falla(worker):
    """Write ausente del comp => se marca 'ausente', no explota (D3)."""

    aplicado = worker.aplicar_qc_spec(
        {"DELIVERY_EXR": {"fps": 23.976}}, toNode=lambda n: None, root=_root_fake()
    )

    assert aplicado["DELIVERY_EXR"] == "ausente"


def test_aplicar_qc_spec_knob_roto_lista_error(worker):
    """Knob format que falla => error listado por knob, el resto aplica (D3)."""

    class _WriteRoto:
        def knobs(self):
            return {"format"}

        def __getitem__(self, k):
            raise RuntimeError("knob no disponible")

    aplicado = worker.aplicar_qc_spec(
        {"DELIVERY_EXR": {"fps": 23.976, "format": "2048x1156"}},
        toNode=lambda n: _WriteRoto(),
        root=_root_fake(),
    )
    assert "errores" in aplicado
    assert any("format" in e for e in aplicado["errores"])
    # el resto de los knobs aplica igual (fps al root) pese al knob roto
    assert aplicado["DELIVERY_EXR"]["fps"] == 23.976


# ---------------------------------------------------------------------------
# RC-MN-02: politica de existencia por tipo (EXR por frame / MOV por archivo)
# ---------------------------------------------------------------------------


def _template(tmp_path, prefijo="deli_V05", n=1, ext="exr"):
    """Crea el archivo tmp_path/{prefijo}.{n:04d}.{ext} y devuelve su ruta."""
    archivo = tmp_path / ("%s.%04d.%s" % (prefijo, n, ext))
    archivo.write_bytes(b"x" * 32)
    return str(archivo)


def test_exr_por_frame_765_faltantes_de_1665(tmp_path, monkeypatch):
    """1665 esperados, 900 existentes => 765 faltantes para render (RC-MN-02)."""
    monkeypatch.setattr(orquestador, "header_exr_valido", lambda p: True)
    template = str(tmp_path / "deli_V05.####.exr")
    for n in range(1001, 1901):  # 900 frames existentes
        _template(tmp_path, n=n)
    existentes = orquestador.frames_existentes(template, 1001, 2665)

    plan = orquestador.plan_nodo(
        {"first": 1001, "last": 2665, "use_limit": False},
        template, 1001, 2665, "keep",
    )

    assert len(existentes) == 900
    assert plan["tipo"] == "sequence"
    assert len(plan["a_render"]) == 765  # 1665 - 900
    assert plan["decision"] == "keep"


def test_exr_politica_replace_renderiza_el_rango_completo(tmp_path, monkeypatch):
    """--politica replace => toda la secuencia, aunque existan frames."""
    monkeypatch.setattr(orquestador, "header_exr_valido", lambda p: True)
    template = str(tmp_path / "deli_V05.####.exr")
    for n in range(1001, 1101):  # 100 existentes
        _template(tmp_path, n=n)

    plan = orquestador.plan_nodo(
        {"first": 1001, "last": 1100, "use_limit": False},
        template, 1001, 1100, "replace",
    )

    assert plan["tipo"] == "sequence"
    assert len(plan["a_render"]) == 100  # nada se salva en replace
    assert sorted(plan["a_render"]) == list(range(1001, 1101))


def test_exr_frames_corruptos_se_re_renderizan(tmp_path, monkeypatch):
    """Un frame existente con header invalido cuenta como corrupto => se re-renderiza."""
    # header valido para todo menos el frame 1042 (bytes invalidos)
    def header_selectivo(path):
        return os.path.basename(path).startswith("deli_V05.1042") is False

    monkeypatch.setattr(orquestador, "header_exr_valido", header_selectivo)
    template = str(tmp_path / "deli_V05.####.exr")
    for n in range(1001, 1003):
        _template(tmp_path, n=n)
    _template(tmp_path, n=1042)  # existe pero "corrupto" (header falso)

    plan = orquestador.plan_nodo(
        {"first": 1001, "last": 1042, "use_limit": False},
        template, 1001, 1042, "keep",
    )

    assert 1042 in plan["corruptos"]
    assert 1042 in plan["a_render"]  # corrupto => no se salva
    assert 1001 not in plan["a_render"]  # valido y existente => se salva
    assert 1002 not in plan["a_render"]


def test_mov_por_archivo_ausente_se_programa_entero(tmp_path):
    """DELIVERY_DWG ausente en disco => se programa el render del archivo (RC-MN-02)."""
    template = str(tmp_path / "delivery_dwg.mov")
    assert not os.path.exists(template)

    plan = orquestador.plan_nodo(
        {"first": 1001, "last": 1665, "use_limit": False},
        template, 1001, 1665, "keep",
    )

    assert plan["tipo"] == "archivo"
    assert plan["existe"] is False
    assert plan["decision"] == "render"
    assert plan["a_render"] == [template]


def test_mov_por_archivo_presente_se_skippea_con_keep(tmp_path):
    """DELIVERY_DWG presente + politica keep => skip (no se re-renderiza)."""
    template = str(tmp_path / "delivery_dwg.mov")
    tmp_path.joinpath("delivery_dwg.mov").write_bytes(b"x" * 32)

    plan = orquestador.plan_nodo(
        {"first": 1001, "last": 1665, "use_limit": False},
        template, 1001, 1665, "keep",
    )

    assert plan["tipo"] == "archivo"
    assert plan["existe"] is True
    assert plan["decision"] == "skip"
    assert plan["a_render"] == []


def test_mov_por_archivo_presente_se_renderiza_con_replace(tmp_path):
    """DELIVERY_DWG presente + politica replace => se re-renderiza entero."""
    template = str(tmp_path / "delivery_dwg.mov")
    tmp_path.joinpath("delivery_dwg.mov").write_bytes(b"x" * 32)

    plan = orquestador.plan_nodo(
        {"first": 1001, "last": 1665, "use_limit": False},
        template, 1001, 1665, "replace",
    )

    assert plan["tipo"] == "archivo"
    assert plan["decision"] == "render"
    assert plan["a_render"] == [template]


def test_mov_con_digitos_en_el_nombre_no_es_secuencia_exr():
    """Threat 'Output existence': .mov con digitos jamas se clasifica sequence."""
    assert orquestador.tipo_salida("plan_v1024.mov") == "archivo"
    assert orquestador.tipo_salida("plan_v005.####.exr") == "sequence"
    assert orquestador.tipo_salida("plan_v005.%04d.exr") == "sequence"
    assert orquestador.tipo_salida("plan_v005.1001.exr") == "sequence"
    assert orquestador.derivar_template("plan_v1024.mov") == "plan_v1024.mov"
    assert orquestador.derivar_template("plan_v005.####.exr") == "plan_v005.####.exr"
    assert orquestador.derivar_template("plan_v005.1001.exr") == "plan_v005.####.exr"


# ---------------------------------------------------------------------------
# RC-MN-02: CALIB/PLAN solo en DELIVERY_EXR + piggyback con use_limit
# ---------------------------------------------------------------------------


def test_exigir_delivery_exr_ok_con_entrega_en_alcance():
    """DELIVERY_EXR en alcance => no aborta (CALIB/PLAN habilitados)."""
    orquestador.exigir_delivery_exr(["DELIVERY_EXR", "DELIVERY_DWG"])


def test_exigir_delivery_exr_aborta_si_el_filtro_lo_excluye():
    """--wnodes sin DELIVERY_EXR => abort claro (sin degradacion, RC-MN-02)."""
    with pytest.raises(SystemExit) as exc:
        orquestador.exigir_delivery_exr(["REVIEW_REC709"])
    mensaje = str(exc.value.code)
    assert "DELIVERY_EXR" in mensaje
    assert "REVIEW_REC709" in mensaje


def test_exigir_delivery_exr_aborta_sin_ningun_nodo():
    """Comp sin nodos de entrega => abort nombrando el alcance vacio."""
    with pytest.raises(SystemExit) as exc:
        orquestador.exigir_delivery_exr([])
    assert "DELIVERY_EXR" in str(exc.value.code)


def test_rango_efectivo_nodo_respeta_use_limit():
    """use_limit activo => rango propio del Write; inactivo => rango de corrida."""
    info_limit = {"first": 1558, "last": 1665, "use_limit": True}
    assert orquestador.rango_efectivo_nodo(info_limit, 1001, 1665) == (1558, 1665)

    info_sin_limit = {"first": 1558, "last": 1665, "use_limit": False}
    assert orquestador.rango_efectivo_nodo(info_sin_limit, 1001, 1665) == (1001, 1665)


def test_env_piggyback_lleva_rangos_propios_de_los_previews():
    """Previews piggyback: 'NAME:first:last' con el rango efectivo (use_limit)."""
    descubiertos = {
        "DELIVERY_EXR": {"first": 1001, "last": 1665, "use_limit": False},
        "REVIEW_REC709": {"first": 1558, "last": 1665, "use_limit": True},
        "SBS_REC709": {"first": 1001, "last": 1665, "use_limit": False},
    }
    env = orquestador.env_piggyback(descubiertos, ["DELIVERY_EXR"], 1001, 1665)

    assert env == "REVIEW_REC709:1558:1665,SBS_REC709:1001:1665"


def test_env_piggyback_excluye_previews_ya_en_alcance():
    """Preview ya seleccionado con --wnodes no se duplica en piggyback."""
    descubiertos = {
        "DELIVERY_EXR": {"first": 1, "last": 90, "use_limit": False},
        "REVIEW_REC709": {"first": 1, "last": 90, "use_limit": False},
    }
    env = orquestador.env_piggyback(descubiertos, ["DELIVERY_EXR", "REVIEW_REC709"], 1, 90)

    assert env is None


def test_env_piggyback_sin_previews_devuelve_none():
    """Sin previews descubiertos => PIGGYBACK no se emite."""
    descubiertos = {"DELIVERY_EXR": {"first": 1, "last": 90, "use_limit": False}}
    assert orquestador.env_piggyback(descubiertos, ["DELIVERY_EXR"], 1, 90) is None


# ---------------------------------------------------------------------------
# RC-MN-03: --force-exr conserva duracion y resolucion
# ---------------------------------------------------------------------------


def test_forzar_template_exr_convierte_mov_a_secuencia_exr():
    """File unico (.mov) => misma base, secuencia ####.exr (RC-MN-03)."""
    forzado = orquestador.forzar_template_exr("/base/FROM_VFX/EP_07/deli.mov")

    assert forzado == "/base/FROM_VFX/EP_07/deli.####.exr"


def test_forzar_template_exr_con_secuencia_exr_queda_igual():
    """Ya exr secuencia => derivar_template normal (sin doble conversion)."""
    assert orquestador.forzar_template_exr(
        "/base/FROM_VFX/EP_07/deli.####.exr"
    ) == "/base/FROM_VFX/EP_07/deli.####.exr"
    assert orquestador.forzar_template_exr(None) is None


# ---------------------------------------------------------------------------
# Mecanica del worker multi-nodo: piggyback con clip y --force-exr
# ---------------------------------------------------------------------------


def test_parsear_piggyback_nombre_con_rango_y_nombre_solo(worker):
    """'NAME:first:last' lleva el rango propio; 'NAME' solo, rango de batch."""
    assert worker._parsear_piggyback(
        "REVIEW_REC709:1558:1665,SBS_REC709"
    ) == [("REVIEW_REC709", 1558, 1665), ("SBS_REC709", None, None)]


def test_parsear_piggyback_vacio_y_malformado(worker):
    """Env vacio o rango ilegible => lista vacia o nombre pelado (sin crash)."""
    assert worker._parsear_piggyback("") == []
    assert worker._parsear_piggyback("RARO:abc") == [("RARO", None, None)]


def test_clip_recorta_el_listado_al_rango_del_nodo(worker):
    """El preview solo ejecuta los frames del batch dentro de su rango."""
    assert worker._clip([1001, 1002, 1003, 1004], 1002, 1003) == [1002, 1003]
    assert worker._clip([1001, 1002], 1558, 1665) == []


def test_forzar_exr_en_reescribe_archivo_unico_a_secuencia_exr(worker):
    """MOV single-file => file a ####.exr y file_type a exr (RC-MN-03)."""
    fake = _WriteFake(file="/base/FROM_VFX/EP_07/deli.mov", file_type="mov")

    modificado = worker.forzar_exr_en(fake)

    assert modificado is True
    assert fake["file"].valor == "/base/FROM_VFX/EP_07/deli.####.exr"
    assert fake["file_type"].valor == "exr"


def test_forzar_exr_en_no_op_con_secuencia_exr(worker):
    """Ya secuencia EXR => no se toca el file (no double-conversion)."""
    fake = _WriteFake(file="/base/FROM_VFX/EP_07/deli.####.exr", file_type="exr")

    assert worker.forzar_exr_en(fake) is False
    assert fake["file"].valor == "/base/FROM_VFX/EP_07/deli.####.exr"


def test_forzar_exr_en_none_devuelve_false(worker):
    """Nodo inexistente (toNode None) => False, sin efecto."""
    assert worker.forzar_exr_en(None) is False


def test_render_branch_clips_piggyback_a_su_rango(monkeypatch):
    """Rama render real: previews se ejecutan recortados a su rango efectivo.

    Con RENDER_LIST 1001..1005 y PIGGYBACK 'REVIEW_REC709:1002:1004', el
    delivery ejecuta 1001-1005 y el preview SOLO 1002-1004 (mismo batch,
    rango propio — RC-MN-02 esc. Preview piggyback with use_limit).
    """
    ejecutados = []
    monkeypatch.setattr(nuke, "scriptOpen", lambda *a, **k: None, raising=False)

    def fake_execute(nodo, a, b):
        ejecutados.append((nodo, a, b))

    monkeypatch.setattr(nuke, "execute", fake_execute, raising=False)
    monkeypatch.setenv("BASE", "/Volumes/wupm/2026")
    monkeypatch.setenv("MODE", "render")
    monkeypatch.setenv("RENDER_LIST", "1001,1002,1003,1004,1005")
    monkeypatch.setenv("PIGGYBACK", "REVIEW_REC709:1002:1004")
    monkeypatch.delenv("WNODES", raising=False)
    monkeypatch.delenv("FORCE_EXR", raising=False)
    monkeypatch.delenv("WNODE", raising=False)
    monkeypatch.delenv("FIRST", raising=False)
    monkeypatch.delenv("LAST", raising=False)
    sys.modules.pop(MODULO_WORKER, None)
    importlib.import_module(MODULO_WORKER)
    try:
        assert ejecutados == [
            ("Write1", 1001, 1005),     # batch del delivery
            ("REVIEW_REC709", 1002, 1004),  # preview solo en su rango
        ]
    finally:
        sys.modules.pop(MODULO_WORKER, None)