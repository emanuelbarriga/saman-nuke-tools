# Tasks: Render asistido por agente con validación de plates (`render-agente-qc`)

## Review Workload Forecast

- Estimated changed lines: ~880–1070 (fuente ~430–500 + tests ~400–470 + docs ~60–90) — sobre presupuesto 400 ⇒ 4 PRs encadenados, auto-chain.

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

### Suggested Work Units (dependency: PR2→PR1, PR3→PR2, PR4→PR3)

- **Unit 1 → PR 1 (~330–380)**: `layouts.py` + `proyectos` config + selección mtime + flags + tests (D1/D2). Tests: `pytest tests/test_seleccion.py tests/test_render_config.py tests/test_no_fuga.py`. Runtime: N/A — pytest puro, mtime `os.utime(tmp_path)`. Rollback: revert layouts.py + flags.
- **Unit 2 → PR 2 (~230–280)**: PROBE multi-nodo + política EXR/MOV + CALIB/PLAN delivery + piggyback + `--force-exr` (D4). Tests: `pytest tests/test_multinodo.py tests/test_render_distribuido.py tests/test_no_fuga.py`. Runtime: N/A — stub nuke, PROBE mockeado. Rollback: revert worker PROBE/env.
- **Unit 3 → PR 3 (~260–320)**: `plate_qc.py` + gate + `qc_set` + overrides + reporte JSON (D3/D5/D6). Tests: `pytest tests/test_qc_plate.py tests/test_render_distribuido.py tests/test_no_fuga.py`. Runtime: N/A — monkeypatch `subprocess.run` (fixture ffprobe). Rollback: revert plate_qc.py + wiring.
- **Unit 4 → PR 4 (~60–90)**: docs SKILL.md + convenciones multi-proyecto. Tests: `python3 -m pytest`. Runtime: suite completa real. Rollback: revert docs.

## Phase 1 · PR 1 — Layout declarativo + selección mtime

> **AJUSTE POR PRESUPUESTO REAL (gatekeeper, 2026-09-02)**: el diff real de
> PR1 midió **1149 líneas** (vs forecast 330–380 y presupuesto 400). PR1 se
> re-slicéó en la cadena stacked-to-main **PR1a → PR1b → PR1c → PR1d → PR1e**,
> cada uno <= ~360 líneas, con test file propio por PR y suite verde por sí
> solo (verificado estado por estado). Orden final de la cadena:
> PR1a (config) → PR1b (layouts data+resolver) → PR1c (plate) → PR1d
> (selección mtime) → PR1e (CLI asistido) → PR2 → PR3 → PR4.

- [x] 1.1 RED `tests/test_layouts.py`: `resolver_planos` remapea `2VFX/Capitulo_7`→`EP_07`, `SC13`→`PFC_SC13`, `104`→IPYD por proyecto (RC-SS-01) — PR1b
- [x] 1.2 RED ídem: mtime gana pese a `_V` menor; tie-break `_V012`>_V005; ignora `.nk~`/`.autosave`/`.tmp`/punto (RC-SS-02) — PR1d
- [x] 1.3 RED ídem: `analizar_version`→`sospechosa=True`; carpeta sin `.nk` aborta nombrando carpeta (RC-SS-02/03) — PR1d
- [x] 1.4 GREEN `render_distribuido/layouts.py`: `Layout` relativo + `resolver_planos`/`localizar_plate`/`mejor_version_comp`/`analizar_version` (D1/D2) — PR1b/c/d
- [x] 1.5 RED `tests/test_render_config.py`: `proyectos` bool válido / string inválido / ausente ⇒ `{}` (RC-CN-02) — PR1a
- [x] 1.6 GREEN `render_config.py` validador `proyectos` aditivo + `studio_config.example.json` (RC-CN-02/05) — PR1a
- [x] 1.7 GREEN `render_distribuido.py`: `--proyecto` (default HTLR+aviso)/`--comp-dir`/`--resolve-latest`/`--use-version` + `[Confirmar]`/`[Ver lista y desmarcar]` (RC-SS-03) — PR1e
- [x] 1.8 GREEN `tests/test_no_fuga.py`: registrar `layouts.py`+`test_layouts.py` (PR1b) y `test_seleccion.py` (PR1d) en `ARCHIVOS_BATCH` (RC-CN-05)

## Phase 2 · PR 2 — Multi-nodo Write

- [x] 2.1 RED `tests/test_multinodo.py`: descubrimiento por nombre real + `--wnodes`; cero "delivery"/"preview"/"side by side" (RC-MN-01)
- [x] 2.2 RED ídem: EXR por frame (765 faltantes de 1665); MOV por archivo; `.mov` con dígitos ≠ sequence (RC-MN-02)
- [x] 2.3 RED `tests/test_render_distribuido.py`: env `WNODES`/`PIGGYBACK` quoting intacto; metacaracteres inertes en argv (threat env)
- [x] 2.4 GREEN `render_worker.py`: PROBE multi-nodo (`nodes`+`root_*` payload) + env `WNODES`/`PIGGYBACK` (D4)
- [x] 2.5 GREEN `render_distribuido.py`: `--wnodes`; `derivar_template` por extensión; `archivo_existente`; CALIB/PLAN solo DELIVERY_EXR; piggyback `use_limit`; `--force-exr` (RC-MN-02/03)
- [x] 2.6 GREEN `tests/test_no_fuga.py`: registrar `test_multinodo.py` (PR2 verde)

## Phase 3 · PR 3 — Gate QC pre-render

- [x] 3.1 RED `tests/test_qc_plate.py`: `probar_plate` parsea fixture ffprobe (ProRes 4444/10-bit/1920x1080/23.976/1665); fallo aborta nombrando ruta (RC-QC-02)
- [x] 3.2 RED ídem: `localizar_plate` fecha_key `20260628-2`>`20260627`; `--plate-date` elige fecha vieja (RC-QC-01)
- [x] 3.3 RED ídem: 24 vs 23.976 abort, `--force-qc` procede; drift preview REC709 1558/1665=warning; naming roto→duración/abort; delivery reescrito (RC-QC-03)
- [x] 3.4 RED `tests/test_render_distribuido.py`: gate PROBE→QC→EXISTENTES; legacy `--comp` sin gate; report `TEST_RENDER/qc_*.json`; exit 3 (RC-QC-04)
- [x] 3.5 GREEN `render_distribuido/plate_qc.py`: `probar_plate` (argv-list JSON)/`comparar` (warning|error)/`reportar`/`decision` (`__DECISION__`) (D3/D5/D6)
- [x] 3.6 GREEN `render_worker.py`: mode `qc_set` reescritura format/fps + env `QC_SET` (D3/D4)
- [x] 3.7 GREEN `render_distribuido.py`: gate wiring + `--force-qc`/`--plate-date`/`--validar-solo-duracion`; overrides auto; `__DECISION__`+exit 3 (D5)
- [x] 3.8 GREEN `tests/test_no_fuga.py`: registrar `plate_qc.py`+`test_qc_plate.py` (PR3 verde)

## Phase 4 · PR 4 — Docs

- [x] 4.1 `skills/render-red/SKILL.md`: flujo agente + layouts HTLR/IPYD/PCF + tabla flags/overrides (proposal #7)
- [x] 4.2 `render_distribuido/README.md`: convenciones multi-proyecto — roles PLATE/DELIVERY/PREVIEW/SBS fijos; layout=dato; PCF `ENTREGAS/` alt (RC-CN-05)
- [x] 4.3 Guard final: `python3 -m pytest` suite completa verde (legacy `--comp` + no_fuga + nuevo) — 634 passed