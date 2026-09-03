# Design: Render asistido por agente con validación de plates (`render-agente-qc`)

## Technical Approach

Flujo asistido por intención ("renderiza los planos del Capítulo 7") que generaliza el orquestador config-driven existente: `layouts.py` declara los layouts físicos por proyecto como DATOS relativos (roles semánticos PLATE/DELIVERY/PREVIEW/SBS fijos en código); `--proyecto/--comp-dir` resuelven carpetas de planos y `mejor_version_comp` elige por mtime real (orquestador, nunca worker); la PROBE se generaliza a multi-nodo (DELIVERY_EXR/DELIVERY_DWG/REVIEW_REC709/SBS_REC709); el gate QC pre-render (`plate_qc.py`) localiza el plate, lo deep-probea con ffprobe y compara contra Root/template con report + abort salvo `--force-qc`; los caminos tristes salen como decisiones estructuradas (Q&A del agente, overrides no interactivos en modo auto). Legacy `--comp` sin flags nuevos queda intacto (RC-QC-04). Mapea proposal #1-#7.

## Architecture Decisions

### Decision: D1 — Layout multi-proyecto como DATOS en código; `proyectos` = enablement aditivo en config

**Choice**: `render_distribuido/layouts.py` declara por proyecto patrones RELATIVOS (raíz `HTLR/`/`IPYD/`/`PCF/` relativa a la base, episodios `EP_n`, secuencias `PFC_SC##`, fechas `YYYYMMDD[-N]`, naming `_comp_SAMAN_`/`_COMP_SAMAN_SE`). `studio_config.json` gana la clave `proyectos` (mapa nombre→bool, aditiva; ausencia válida — RC-CN-02). `resolver_planos(intent)` remapea intenciones no literales ("2VFX/Capitulo_7" → `EP_07`) al patrón real del proyecto (RC-SS-01).
**Alternatives considered**: (a) layouts completos en el JSON administrado (`proyectos` con patrones anidados) — rechazada: schema anidado complejo en `validar_esquema` (hoy valida solo 3 claves de primer nivel + workers, `render_config.py:48`), fixture de ejemplo difícil de mantener, y `test_no_fuga` ya escanea archivos de código (`tests/test_no_fuga.py:31`); (b) HTLR-only con arquitectura lista — rechazada (proposal #1, corrección del usuario: IPYD/PCF tienen layouts propios).
**Rationale**: el precedente render-config-central fijó "dominio = rol, no layout" (RC-CN-05 delta); los patrones físicos son datos que evolucionan con review de código y quedan bajo el guard anti-fuga (cero raíces absolutas, `test_no_fuga.py:47-49`). La config solo habilita/deshabilita proyectos — validador aditivo sin romper configs legacy. Evidencia: hoy el orquestador ya recibe `--comp` RELATIVO a la base del worker (`env_worker` compone `COMP = worker["base"] + "/" + args.comp`, `render_distribuido.py:150`) — el layout relativo encaja sin tocar el contrato remoto.
**Spec**: RC-SS-01 (todos los escenarios), RC-CN-02 (esc. Proyectos absent/Invalid), RC-CN-05 (Layout data is relative, Semantic roles fixed).

### Decision: D2 — Selección por mtime con política exacta y aviso de falso positivo

**Choice**: `mejor_version_comp(plan_dir)` filtra `*.nk` por patrón `_comp_SAMAN_` del proyecto, descarta `.nk~`/`.autosave`/puntos/temp, ordena por `os.path.getmtime` descendente (mtime SO; LucidLink colapsa ctime/birthtime, proposal-métrica); tie-break `_V\d+` mayor; mtime medido SIEMPRE en el orquestador iMac (monte local), nunca en workers. `analizar_version(dir)` devuelve `{elegida, candidatas, sospechosa}`: `sospechosa=True` si la elegida por mtime NO es la de mayor `_V` → aviso + decisión 1-clic [Usar más reciente]/[Usar v015].
**Alternatives considered**: (a) V-number como clave (rechazada: métrica de exploración 15/46 carpetas HTLR con multi-`_comp_SAMAN_V*.nk` donde V NO es clave); (b) mtime medido por workers (rechazada: LucidLink colapsa ctime/birthtime — el worker remoto no ve el mtime real del monte del orquestador).
**Rationale**: RC-SS-02 exige mtime con tie-break; la sospecha se modela como dato (no heurística de abort) para que la UI la presente y el flag `--use-version V\d+` la resuelva en auto. Carpeta sin `.nk` calificante ⇒ abort nombrando la carpeta (RC-SS-03, política estricta existente: nunca skip silencioso).
**Spec**: RC-SS-02 (3 escenarios), RC-SS-03 (No comp found).

### Decision: D3 — Gate QC pre-render ON por defecto en flujo asistido

**Choice**: gate activo solo cuando la corrida es asistida (cualquier flag nuevo presente); legacy `--comp` sin flags nuevos NO gatilla (RC-QC-04 Legacy run). `localizar_plate(proyecto, plano, config)` elige la fecha más reciente (`fecha_key` ordena `20260628-2` > `20260627`, RC-QC-01) con `--plate-date` de override. `ffprobe` vía `subprocess.run` con argv-list (sin shell), stdout JSON parseado a dict (codec ProRes 4444 / bit-depth / colorspace / res / fps / frames); fallo de probe ⇒ abort nombrando la ruta (RC-QC-02). Comparación: plate vs Root del comp (fps/format/first-last) y vs template de entrega; discrepancia error en frames/fps/res ⇒ report + abort salvo `--force-qc`, y el nodo de entrega SE REESCRIBE a las specs del plate (worker mode `qc_set`); drift SOLO en nodos PREVIEW ⇒ warning del report, no abort (caso real EP_108 1558 vs 1665).
**Alternatives considered**: gate siempre activo (rompe RC-QC-04 legacy); gate por defecto OFF con `--qc` opt-in (invierte la seguridad por defecto, proposal #3).
**Rationale**: la PROBE actual ya provee `plate_first/plate_last` y `wnode_file` (`render_worker.py:134-157`, `rango_plate` al anchor PLATE); extender su payload (root fps/format + nodes) es aditivo y reutiliza `ejecutar`/`parsear_worker_out`. El gate corre tras PROBE y antes de EXISTENTES (puede reescribir el nodo de entrega y abortar temprano sin gastar granja). `derivar_template` hoy es EXR-céntrico (`TEMPLATE_EXPR = re.compile(r"(\d{4})(?=\.exr$)")`, `render_distribuido.py:251-258`) — la comparación de frames usa el template evaluado del nodo delivery reportado en PROBE.
**Spec**: RC-QC-01, RC-QC-02, RC-QC-03 (FPS mismatch, Preview drift, Delivery overwritten), RC-QC-04 (ambos escenarios).

### Decision: D4 — Multi-nodo: descubrimiento real + política por nodo + CALIB/PLAN solo entrega EXR

**Choice**: PROBE generalizada: el worker emite por nodo `{first, last, file, file_type}` para cada Write hallado por nombre real entre `DELIVERY_EXR/DELIVERY_DWG/REVIEW_REC709/SBS_REC709` + `root_fps/root_first/root_last/root_w/root_h`; `--wnodes` filtra (RC-MN-01). Política de existencia por tipo: EXR ⇒ por frame (`frames_existentes`), MOV ⇒ por archivo (helper nuevo `archivo_existente`); `derivar_template` se generaliza por extensión (EXR `####.exr` vs MOV literal). CALIB/PLAN solo sobre `DELIVERY_EXR` (RC-MN-02): si el filtro lo excluye o no existe ⇒ abort claro (sin degradación). Previews (`REVIEW_REC709`/`SBS_REC709`) piggyback en el mismo batch del delivery respetando `use_limit` (env `PIGGYBACK`; `nuke.execute` con los mismos rangos, el Write confina por sus first/last). `--force-exr` obliga salida EXR-sequence del nodo delivery conservando duración/resolución (RC-MN-03).
**Alternatives considered**: mantener `--wnode` único (rompe proposal #4 y el drift REC709 ya detectado); label-friendly ("delivery") como nombre de nodo (viola RC-MN-01 y el mapping real del comp).
**Rationale**: `perf_nodo(nombre)` (`render_worker.py:80`) y `ejecutar_frames(wnode, lista)` (`render_worker.py:66`) ya parametrizan por nombre — reutilizables sin refactor estructural. La rotura de naming plate↔write no se empareja en silencio: toma la ruta de decisión D5c.
**Spec**: RC-MN-01 (2 escenarios), RC-MN-02 (4 escenarios), RC-MN-03.

### Decision: D5 — Caminos tristes como Q&A del agente: CLI emite decisión estructurada; overrides no interactivos

**Choice**: el CLI nunca bloquea con panel: emite `__DECISION__{...}` (JSON: id, problema, opciones, default) por stdout y, en TTY, `input()`; en modo auto ABORTA con el bloque estructurado (exit code dedicado) para que el agente pregunte y re-invoque con el override. Overrides: (a) mtime falso positivo → `--use-version V\d+` (default: más reciente por mtime); (b) multiplicidad de fechas → `--plate-date YYYYMMDD[-N]` (default: más reciente); (c) naming roto plate↔write → `--validar-solo-duracion` (prosigue solo con duración) o abort; (d) fps 24 vs 23.976 → reescritura al fps del plate + `--force-qc` para proceder (default: abort). `--resolve-latest` confirma en silencio la selección mtime (RC-SS-03).
**Alternatives considered**: panel Nuke/dashboard (decisión tomada: Q&A del agente, proposal Out of Scope); flags que bloquean esperando stdin en auto (rompe orquestación no interactiva).
**Rationale**: el orquestador ya es headless (`input()` solo en `politica_reemplazo`, `render_distribuido.py:396`, con EOFError→"n"); el contrato JSON es la superficie estable entre CLI y agente, y cada decisión mapea 1:1 a un flag sin ambigüedad.
**Spec**: RC-SS-02 (override v015), RC-QC-01 (override otra fecha), RC-QC-03 (naming, fps), RC-QC-04 (force).

### Decision: D6 — Formato de salida del QC: reporte JSON por proyecto/corrida + resumen stdout

**Choice**: reporte en `TEST_RENDER/qc_<proyecto>_<YYYYmmdd_HHMMSS>.json` (relativo a la base, misma convención que `FROM_SUF="/TEST_RENDER/calib_<worker>/"` de CALIB, `render_distribuido.py:177`) + resumen en stdout. Contenido mínimo: `{proyecto, planos: [{plano, version_elegida, mtime, sospechosa, candidatas}], plates: [{plano, fecha, ruta_relativa, ffprobe:{codec,bit_depth,colorspace,res,fps,frames}}], discrepancias: [{severidad: warning|error, tipo, nodo, campo, esperado, encontrado, decision}]}`. Las discrepancias `error` listadas son las que abortan sin `--force-qc` (RC-QC-04 Report emitted).
**Alternatives considered**: solo stdout (se pierde el artefacto para auditoría/re-invocación del agente); reporte por plataforma no render (innecesario en v1).
**Rationale**: el JSON es consumible por el agente para la Q&A (D5) y por verify; `test_no_fuga` escanea código, no runtime — el reporte lleva rutas RELATIVAS (la plana de datos ya es relativa por D1).
**Spec**: RC-QC-04 (Report emitted with force).

## Data Flow

```
intent "Capitulo 7" + --proyecto HTLR
  → layouts.resolver_planos(intent)            [D1] raíz relativa + bases_por_so → carpetas reales
  → layouts.mejor_version_comp(por plano)      [D2] mtime orquestador + tie-break; sospechosa?
      → [Confirmar]/[Ver lista y desmarcar] | --resolve-latest | --use-version
  → PROBE extendida (worker)                   [D4] root fps/format + nodes{first,last,file,type} + plate range
  → plate_qc: localizar_plate() → ffprobe()    [D3] plate fecha más reciente (override --plate-date)
  → comparación plate vs Root vs template → discrepancias
      → [D5] __DECISION__ Q&A | overrides | abort · reporte D6
  → (reescritura nodo delivery vía mode qc_set si difiere)
  → EXISTENTES por nodo (EXR por frame / MOV por archivo) → POLITICA
  → CALIB (solo DELIVERY_EXR) → PLAN → RENDER (delivery + PIGGYBACK previews, --force-exr)
  → TEST_RENDER/qc_*.json + RESUMEN
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `render_distribuido/layouts.py` | Create | Layouts declarativos por proyecto (patrones relativos, `fecha_key`, `patron_comp`, `resolver_planos`, `localizar_plate`, `mejor_version_comp`, `analizar_version`) — D1/D2 |
| `render_distribuido/plate_qc.py` | Create | `ffprobe` (argv-list, JSON), parse, comparación vs Root/template, modelo de reporte, `__DECISION__` — D3/D5/D6 |
| `render_distribuido/render_distribuido.py` | Modify | Flags `--proyecto/--comp-dir/--resolve-latest/--use-version/--wnodes/--force-qc/--plate-date/--validar-solo-duracion/--force-exr`; wiring selección → PROBE extendida → gate QC → multi-nodo; `derivar_template` generalizado + `archivo_existente`; reporte D6 |
| `render_distribuido/render_worker.py` | Modify | PROBE multi-nodo (payload nodes + root), mode `qc_set` (reescritura format/fps), `PIGGYBACK`, `FORCE_EXR` |
| `render_distribuido/render_config.py` | Modify | Validador: `proyectos` (mapping bool, aditivo, ausencia válida) — RC-CN-02 |
| `render_distribuido/studio_config.example.json` | Modify | `proyectos` con HTLR/IPYD/PCF → true (valida, sin datos reales) |
| `tests/test_seleccion.py` | Create | Layout por proyecto, remapeo intent, mtime pese a V menor, tie-break, ignore autosave, sospechosa, flags — D1/D2 |
| `tests/test_qc_plate.py` | Create | ffprobe desde fixture JSON, fecha más reciente `-2`, comparación/severidad, abort vs `--force-qc`, reporte — D3/D5/D6 |
| `tests/test_multinodo.py` | Create | Descubrimiento por nombre real, `--wnodes`, política EXR/MOV, CALIB solo entrega EXR, piggyback, no friendly-label leak — D4 |
| `tests/test_no_fuga.py` | Modify | Sumar `layouts.py`/`plate_qc.py`/tests nuevos a `ARCHIVOS_BATCH` (RC-CN-05 esc. Sanitized) |
| `tests/test_render_config.py` | Modify | Escenarios `proyectos` (válido, inválido, ausente) |
| `skills/render-red/SKILL.md` | Modify | Flujo agente asistido + convenciones multi-proyecto (proposal #7) |

## Interfaces / Contracts

```python
# layouts.py — datos relativos, cero raíces absolutas (test_no_fuga)
@dataclass
class Layout:
    raiz: str                       # "HTLR/", "PCF/", "IPYD/" (relativo a base)
    episodio: Callable[[str], str]  # "capitulo 7"→"EP_07"; "104"→"104"; "SC13"→"PFC_SC13"
    comps: str                      # "COMP/{ep}/" — patrón de carpeta relativo
    plate: str                      # "TO_VFX/{ep}/{fecha}/{plan}.mov" (IPYD: fechas "-N")
    entrega: str                    # "FROM_VFX/{ep}/{fecha}/{tipo}/"  (PCF: "ENTREGAS/COMP/{seq}/")
    patron_comp: str                # regex del .nk candidato (ej. "_comp_SAMAN_V\d+\.nk$")
    version_re: str                 # "_V(\d+)" (IPYD sin _V ⇒ tolerante, tie-break = -1)
def resolver_planos(intent, proyecto, config) -> list[str]        # carpetas relativas a base (RC-SS-01)
def localizar_plate(layout, plano, config, fecha=None) -> str     # fecha más reciente, override (RC-QC-01)
def mejor_version_comp(plan_dir) -> str                           # mtime orquestador + tie-break (RC-SS-02)
def analizar_version(plan_dir) -> dict                            # {elegida, candidatas, sospechosa}

# plate_qc.py
def probar_plate(ruta) -> dict            # subprocess ffprobe argv-list, JSON parse (RC-QC-02)
def comparar(plate, root, template) -> list[dict]  # severidad warning|error por discrepancia (RC-QC-03)
def reportar(corrida, planos, plates, discrepancias) -> str       # TEST_RENDER/qc_*.json (D6)
def decision(id, problema, opciones, default) -> dict | None      # __DECISION__ (D5)

# env worker (ORQUESTADOR) — contrato D6 explicit-env extendido:
#   WNODES="DELIVERY_EXR,REVIEW_REC709" · PIGGYBACK="REVIEW_REC709,SBS_REC709"
#   QC_SET='{"DELIVERY_EXR":{"fps":23.976,"format":"2048x1156"}}' · FORCE_EXR="1"
# PROBE payload extendido: {root_fps, root_first, root_last, root_w, root_h,
#   nodes: {<nombre>: {first, last, file, file_type}}, plate_first, plate_last}
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit (selección) | mtime gana pese a V menor (RED primero); tie-break `_V012` vs `_V005`; `.nk~`/`.autosave`/temp ignorados; sospechosa=True; carpeta sin `.nk` aborta nombrando la carpeta; remapeo `2VFX/Capitulo_7`→`EP_07`, `SC13`→`PFC_SC13`, `104`→IPYD | pytest + `tmp_path` (mtime seteado con `os.utime`), sin Nuke |
| Unit (layout) | `fecha_key`: `20260628-2` > `20260627`; raíces relativas; `test_no_fuga` sobre `layouts.py` con cero IPs/`@`/absolutas | pytest + guard existente |
| Unit (QC) | parse de fixture JSON de ffprobe (ProRes 4444/10-bit/1920x1080/23.976/1665); fallo de probe aborts nombrando ruta; 24 vs 23.976 aborta sin `--force-qc` y procede con él; preview drift = warning; nombre roto → duración-only o abort; nodo delivery reescrito | `plate_qc` puro con `monkeypatch.subprocess.run` sobre fixture |
| Unit (multinodo) | descubrimiento por nombre real y filtro `--wnodes`; EXR por frame (765 faltantes de 1665); MOV por archivo; CALIB/PLAN solo en DELIVERY_EXR; mapping sin "delivery"/"preview"/"side by side" | pytest puro + `test_no_fuga`-style scan del mapping |
| Unit (config) | `proyectos` bool válido, string inválido, ausente ⇒ válido legacy | extender `tests/test_render_config.py` |
| Integration | PROBE payload extendido (mock worker emit); gate en secuencia PROBE→QC→EXISTENTES→POLITICA→CALIB→PLAN→RENDER; legacy `--comp` sin flags ⇒ sin gate | pytest con stub nuke + monkeypatch `ejecutar` |
| E2E | — | N/A (stub nuke; knobs reales de reescritura = check manual en tareas, como `render_worker` hoy) |

## Threat Matrix

| Boundary | Applicability |
|---|---|
| Documentation-like paths | N/A — solo `.py`/`.json`/`.md` no ejecutables |
| Git repository selection | N/A — sin lógica git nueva |
| Commit state | N/A — sin index/worktree automation |
| Push state | N/A — sin refspec/push automation |
| PR commands | N/A — sin composición de comandos PR |
| **ffprobe subprocess (`plate_qc.probar_plate`)** | **Applicable** — nuevo `subprocess.run` con argv-list |
| **Remote command/env composition (`ejecutar`)** | **Applicable** — env extendido (WNODES/PIGGYBACK/QC_SET/FORCE_EXR) sobre el contrato D6 existente |
| **Comp-version file classification (`mejor_version_comp`)** | **Applicable** — qué `.nk` cuenta como versión y cuáles se ignoran |
| **Output existence classification (`derivar_template` generalizado)** | **Applicable** — EXR sequence vs MOV single-file; no clasificar mal un `.mov` con dígitos |

**ffprobe subprocess**: safe = argv como lista (`["ffprobe", "-v","error","-print_format","json","-show_streams","-show_format", ruta]`), nunca `shell=True`; ruta del plate como argv (espacios/comillas inertes); parse estricto del JSON; failure behavior = fallo/parse inválido ⇒ aborto nombrando la ruta, jamás default silencioso; RED test = monkeypatch `subprocess.run` devolviendo fixture y otro lanzando returncode≠0.

**Remote command/env composition (extendido)**: safe = mismas reglas D6 (`env KEY='val' ...` inline, argv list, nombres de nodos filtrados en Python y jamás al shell); failure = ssh no-cero propagado, nunca éxito fingido; RED test = `subprocess.run` recibe `QC_SET='{"DELIVERY_EXR":{...}}'` con quoting intacto y un nodo con metacaracteres queda inerte en el argv.

**Comp-version classification**: safe = regex `patron_comp` + exclusión de `.nk~`, `.autosave`, puntos/temp, case-insensitive; failure = carpeta sin candidato ⇒ abort con nombre de carpeta; RED tests = un test por clase adversaria (tilde, autosave, punto, temp).

**Output existence classification**: safe = tipo derivado de extensión del `file` evaluado (`.exr` ⇒ sequence; `.mov` ⇒ archivo único; `####`/`%0Nd` ⇒ sequence); failure = template no derivable ⇒ sin políticos sobre ese nodo (report), nunca falsa existencia; RED test = `.mov` con dígitos en el nombre no se confunde con sequence EXR.

Filas Applicable se propagan a `tasks.md` como RED tests sin modificación.

## Migration / Rollout

Sin migración: `proyectos` es aditiva (RC-CN-02 — configs legacy siguen cargando). Layouts en código = sin cambio de schema en disco. Rollback = `git revert` por PR encadenado (layout → multi-nodo+QC → docs), independientes; legacy `--comp` preservado por defaults de flags nuevos (RC-QC-04).

## Review Workload Forecast (para sdd-tasks)

| Unit | Goal | Likely PR | Test command | Rollback |
|------|------|-----------|--------------|----------|
| 1 | `layouts.py` + `proyectos` en config/example + flags `--proyecto/--comp-dir/--resolve-latest/--use-version` + `tests/test_seleccion.py` + deltas `test_no_fuga`/`test_render_config` (D1/D2) | PR 1 (~330–380) | `pytest tests/test_seleccion.py && pytest tests/test_no_fuga.py` | revert layouts.py + flags |
| 2 | PROBE multi-nodo + política EXR/MOV + CALIB/PLAN entrega + piggyback + `--force-exr` (D4) | PR 2 (~230–280) | `pytest tests/test_multinodo.py tests/test_render_distribuido.py` | revert worker/probe |
| 3 | `plate_qc.py` + gate + reescritura + overrides QC + reporte (D3/D5/D6) | PR 3 (~260–320, depende de PR2) | `pytest tests/test_qc_plate.py` | revert plate_qc.py + gate wiring |
| 4 | Docs: `skills/render-red/SKILL.md` + README convenciones multi-proyecto (proposal #7) | PR 4 (~60–90) | `python3 -m pytest` | revert docs |

Estimado ~880–1070 líneas totales (fuente ~430–500 + tests ~400–470 + docs ~60–90) — por encima del presupuesto de 400 ⇒ cadena de 4 PRs (`auto-chain`). `Decision needed before apply`: No si auto-chain aceptado; `Chained PRs recommended`: Yes; `400-line budget risk`: High.

## Open Questions

- [ ] IPYD: variantes de comp sin `_V` (naming `_COMP_SAMAN_SE`): tie-break cae a mtime puro — confirmar si existe alguna versión IPYD con `_V\d+` en storage real (affecta `version_re` por proyecto).
- [ ] PCF: plates viven en `FROM_VFX/PFC_SC##/YYYYMMDD/` Y `ENTREGAS/COMP/SC##/` — diseño usa `FROM_VFX` (mismo patrón que HTLR/IPYD); documentar `ENTREGAS` como alternativa en SKILL.md.
- [ ] Knobs reales de reescritura (`format`/`fps` sobre Write de entrega) no son testeables con el stub nuke — tarea de apply debe incluir check manual en worker real (mismo estatus que `render_worker` hoy).
- [ ] Convención de exit code para "necesita decisión" (propuesta: 3) — fijar en sdd-tasks para que el agente la detecte sin ambigüedad.