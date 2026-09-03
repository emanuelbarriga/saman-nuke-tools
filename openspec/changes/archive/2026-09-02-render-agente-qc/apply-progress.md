# Apply Progress — render-agente-qc

**Change**: render-agente-qc (2026-09-02)
**Mode**: Strict TDD (`openspec/config.yaml testing.strict_tdd: true`)
**Chain**: stacked-to-main — re-slice PR1a → PR1b → PR1c → PR1d → PR1e → PR2 → PR3 → PR4
**Fuente**: obs Engram 2264 (apply-progress PR2+PR3) y 2265 (PR4 docs); commit materializados en main local por el orquestador.

## Re-slice por presupuesto (gatekeeper, 2026-09-02)

El diff real de PR1 midió 1149 líneas (vs forecast 330–380 y presupuesto 400). PR1 se
re-slicéó en la cadena stacked-to-main **PR1a → PR1b → PR1c → PR1d → PR1e**, cada uno
<= ~360 líneas, con test file propio por PR y suite verde por sí solo (verificado
estado por estado). Orden final: PR1a (config) → PR1b (layouts data+resolver) → PR1c
(plate) → PR1d (selección mtime) → PR1e (CLI asistido) → PR2 → PR3 → PR4.

Los commits NO están agrupados exactamente como el re-slice sino como work units
coherentes (ver tasks.md); la agrupación final de PRs/push la decide el orquestador
en el gate de entrega (fuera del alcance de archive).

## PR2 — Multi-nodo Write (tareas 2.1–2.6, commits 09626c4/c357295/01ad4f9)

Worker PROBE multi-nodo (payload nodes{first,last,use_limit,file,file_type}+root_fps/first/last/w/h),
orquestador `--wnodes` (filtro por descubrimiento, default rol entrega), política por nodo
EXR-por-frame/MOV-por-archivo, CALIB/PLAN solo DELIVERY_EXR (abort si filtro lo excluye),
previews piggyback con rango propio name:first:last, `--force-exr` a secuencia conservando specs.

Tests: tests/test_multinodo.py (30+4), tests/test_render_distribuido.py (+5), tests/test_no_fuga.py (+registro PR2).

## PR3 — Gate QC pre-render (tareas 3.1–3.8, commits f1185f5/96db807/8cc1247/3539e5b)

Módulo nuevo stdlib-only `render_distribuido/plate_qc.py` (probar_plate ffprobe argv-list sin shell +
parse JSON estricto/ProbeError nombrando ruta; fps racional 24000/1001; frames=duración x fps redondeado;
normalizar_id_plano quitando números de frame/.####/_V/comp_SAMAN; comparar plate vs root vs nodos con
severidad warning|error — drift preview REC709=warning, fps/resolución/duración-naming delivery=error;
resolver_gate exit 3 sin --force-qc con overrides validar-solo-duracion y fps-forzar; reporte D6 en
TEST_RENDER/qc_<proyecto>_<ts>.json; decision __DECISION__ JSON con None en auto; spec_qc_set
fps/format/first/last). Worker: mode qc_set (aplicar_qc_spec: fps al root, format+first/last al Write;
errores por knob) + QC_SET aplicado en render por sesión. Orquestador: flags --force-qc/--plate-date/
--validar-solo-duracion/--fps-forzar; gate_qc tras PROBE antes de EXISTENTES/CALIB; exit 3 auto;
QC_SET en env render con quoting intacto.

Tests: tests/test_qc_plate.py (nuevo, 32), tests/test_render_distribuido.py (+7), tests/test_no_fuga.py (+registro PR3).

## PR4 — Docs + cierre (tareas 4.1–4.3, commit bc8ad6f)

skills/render-red/SKILL.md (v2.0, flujo asistido, roles fijos + layout=dato, multi-nodo, gate QC, exit 3)
y render_distribuido/README.md (convención multi-proyecto, tabla de flags, flujo QC, exit codes, caminos tristes).
Marque 4.1–4.3 [x] en tasks.md. Suite completa: 634 passed.

## Suite y evidencia

- Baseline suite: 548 → 584 → 634 passed (verde en cada PR).
- **Suite final (verify re-verificado)**: 634 passed (exit 0); test_no_fuga 41 passed, 0 fugas; py_compile exit 0.
- Evidencia TDD por PR: archivos RED primero, GREEN en el commit de cada work unit.

## Notas / gotchas (del apply)

1. normalizar_id_plano: el número de frame (.0100/.####) se quita DESPUÉS de la extensión, no antes (regex `\.[\d#%]+$` solo al final).
2. ffprobe real EP_108: pix_fmt yuv444p12le (12-bit), 24000/1001, duración 69.444375 ⇒ 1665 frames exactos.
3. root() en el stub de tests no es callable: inyectar `root=lambda: fake`.
4. Knobs reales de reescritura (root fps / write format / first-last) no testeables con stub: **check manual en worker real pendiente** (W3; design.md Open Questions).
5. tests/test_layouts.py y test_seleccion.py re-slicéados: los commits 164973d (+test_layouts −test_seleccion) y bc8ad6f cierran el residuo sin commitear (W5 resuelto en verify).

## Estado al cierre

25/25 tareas `[x]`, 0 incompletas. Suite 634 passed (árbol completo). Sin push: los commits quedan en main local para el gate de entrega del orquestador.