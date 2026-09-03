# Propuesta: Render asistido por agente con validación de plates (`render-agente-qc`)

## Intención

El orquestador renderiza UN comp por invocación (`--comp/--wnode/--sufijos`) fijado al layout HTLR. El usuario pide un flujo asistido: "renderiza los planos del Capítulo 7" → el agente elige el .nk correcto, detecta nodos Write, valida contra el plate (Regla de Oro) y rinde en granja, con decisiones 1-clic en caminos tristes.

**Corrección del usuario (vínculo)**: NO hay convención de storage universal; cada `/2026/<PROYECTO>/` tiene su layout. Verificado: HTLR (episodios `EP_n`; comps `COMP/EP_n/<plan>_comp_SAMAN_V###/`; plates `TO_VFX/EP_n/YYYYMMDD/<plan>.mov`; entregas `FROM_VFX/EP_n/YYYYMMDD/{DWG,REC709}/`), IPYD (episodios `101..106`; comps `COMP/<ep>/<plan>_COMP_SAMAN_SE/`; fechas con sufijo `-2` ej. `20260628-2`; naming `IPYD_104_010_COMP_SAMAN_SE`), PCF (secuencias `PFC_SC##`; comps `COMP/PFC_SC##/<plan>/`; plates/entregas `FROM_VFX/PFC_SC##/YYYYMMDD/` y `ENTREGAS/COMP/SC##/`; naming `PFC_SC13_010_comp_SAMAN_V01.mov`).

**`2VFX/Capitulo_7` NO existe en storage**: la intención se mapea al layout real por proyecto (HTLR→episodio `EP_07`; PCF→secuencia `PFC_SC##`; IPYD→episodio numérico). Diseño no asume HTLR.

Métricas de contexto válidas (exploración): 15/46 carpetas HTLR con multi-`_comp_SAMAN_V*.nk` (V-number NO es clave; mtime SÍ — LucidLink colapsa ctime/birthtime). REC709 EP_108 = 1558 frames vs plate 1665 (drift real).

## Stakeholder Value

Artista pide render granja sin rutear manualmente comp/plate; agente reduce error (versión equivocada, plate mal emparejado, fps/naming rotos) y da visibilidad QC antes de gastar granja.

## Alcance

### In Scope
1. **Layout multi-proyecto declarado**: HTLR + IPYD + PCF como casos; raíz por proyecto desde `studio_config.json` (`bases_por_so` + `proyectos`).
2. **Selección por mtime real**: `mejor_version_comp(plan_dir)` → .nk más reciente (mtime SO; ignorar `.nk~`, `.autosave`, temp); tie-break `_V\d+`; `[Confirmar]` / `[Ver lista y desmarcar]`.
3. **Granja**: checkboxes [PC1, PC2] → `--workers` (UI = Q&A del agente en OpenCode, no panel Nuke — decisión tomada).
4. **Multi-nodo Write**: DELIVERY_EXR, DELIVERY_DWG, REVIEW_REC709, SBS_REC709; EXR por frame, mov por archivo; CALIB/PLAN solo en nodo entrega; previews piggyback.
5. **QC gate pre-render (Regla de Oro)**: localizar plate en layout del proyecto (fecha más reciente), ffprobe profundo (codec ProRes 4444/10-bit, colorspace, res, fps, frames), comparar vs Root del comp y template de entrega; validar/sobrescribir nodo delivery; discrepancias → report + abort salvo `--force-qc`.
6. **Caminos tristes 1-clic**: (a) falso positivo mtime → [Usar más reciente]/[Usar v015]; (b) multiplicidad de fechas → [Usar más reciente]/[Usar otra]; (c) naming roto → [Validar solo duración]/[Abortar]; (d) fps 24 vs 23.976 → [Forzar 23.976]/[Cancelar].
7. **Docs**: `skills/render-red/SKILL.md` + definición de convenciones (PLATE/DELIVERY/_comp_SAMAN_) multi-proyecto.

### Out of Scope
- Panel Nuke / UI tipo dashboard (decisión tomada: Q&A del agente).
- QC profundo por nodo preview contra plate (v2; en v1 el drift EP_108 es warning del report, no abort).
- Batch multi-proyecto en un run (v1: un proyecto por invocación, `--proyecto`).
- Sanitizar gizmos/versionados existentes con rutas HTLR (follow-up del precedente render-config-central).

## Capacidades

### Nuevas
- `render-shot-selection`: resolución layout→carpetas de planos (episodio/secuencia según proyecto), `mejor_version_comp` por mtime con tie-break, lista confirmar/desmarcar, flags `--proyecto/--comp-dir/--resolve-latest`.
- `render-qc-plate`: localización del plate (fecha más reciente con override), ffprobe profundo, comparación vs Root/template, decisión 1-clic por discrepancia, report + abort salvo `--force-qc`, sobrescritura del nodo delivery.
- `render-multinodo`: descubrimiento de nodos Write reales del comp, política de existencia por nodo (EXR por frame, mov por archivo), render/calib solo en el de entrega, previews piggyback.

### Modificadas
- `render-config-central`: los sufijos HTLR dejan de ser "dominio fijo"; los ROLES semánticos (PLATE/DELIVERY/PREVIEW/SBS) permanecen fijos en código y los patrones físicos de carpetas se declaran por proyecto como datos; la raíz resuelve por `bases_por_so` + `proyectos`.

## Enfoque (decisiones con tradeoff)

| # | Decisión | Tradeoff |
|---|----------|----------|
| 1 | **v1 multi-proyecto declarado (HTLR+IPYD+PCF)** — no HTLR-only con arquitectura lista | +80–120 líneas de tabla vs. diseño que rompe con el próximo proyecto; la corrección del usuario lo exige |
| 2 | Layout como **DATOS en código** (`render_distribuido/layouts.py`: patrones relativos EP_/SC##/fechas/-2/_SE, sin rutas absolutas → `test_no_fuga` seguro); config solo habilita proyectos | Mantiene público el repo; resuelve la tensión con render-config-central: dominio = rol, layout = dato |
| 3 | **QC gate ON por defecto**; `--force-qc` procede pese a discrepancias | Seguridad por defecto vs. bloqueos legítimos (force explícito) |
| 4 | **Multi-nodo completo** (EXR+DWG+REC709+SBS): probe/EXISTENTES/política en todos; render/calib solo EXR delivery | Más superficie de test vs. ignorar drift de previews ya detectado |
| 5 | Plate = fecha más reciente gana (IPYD `20260628-2` > `20260627`) con [Usar otra] | Correcto por defecto, override 1-clic cuando la entrega vieja es la buena |

CLI: `--proyecto` (default HTLR, con aviso), `--comp-dir`, `--resolve-latest`, `--wnodes`, `--force-qc`. Backward compat: sin flags nuevos, flujo legacy `--comp` intacto.

## Áreas Afectadas

| Área | Impacto | Cambio |
|------|---------|--------|
| `render_distribuido/layouts.py` | New | layouts declarativos por proyecto (patrones relativos) |
| `render_distribuido/plate_qc.py` | New | ffprobe profundo + comparación + decisiones 1-clic |
| `render_distribuido/render_distribuido.py` | Modified | `--proyecto/--resolve-latest/--wnodes/--force-qc`, selección mtime, multi-nodo |
| `render_config.py` + `studio_config.example.json` | Modified | clave `proyectos` (habilitar/deshabilitar) |
| `skills/render-red/SKILL.md` | Modified | flujo agente + convenciones multi-proyecto |
| `tests/test_seleccion.py`, `tests/test_qc_plate.py`, `test_no_fuga.py` | New/Modified | pytest con nuke stub |

## Riesgos

| Riesgo | Prob. | Mitigación |
|--------|-------|------------|
| mtime no confiable fuera de iMac (LucidLink colapsa ctime/birthtime) | Med | mtime medido desde el orquestador; documentado |
| Falso positivo mtime (v001 tocado hoy vs v015 aprobado) | Med | decisión 1-clic [Usar v015] |
| Naming roto plate↔write / fps discordante | Med | caminos tristes 1-clic + report QC |
| Base no montada / config ausente en QC | Low | abort claro sin degradación silenciosa (política estricta existente) |
| Footprint > 400 líneas (presupuesto 400) | Med | PRs encadenados (auto-chain): PR1 layout+selección, PR2 multi-nodo+QC, PR3 docs |
| Regresión del flujo legacy `--comp` | Low | defaults backward-compat + suite existente |

## Rollback

- `git revert` por PR encadenado (layout → selección → QC → docs), independientes.
- Comportamiento legacy `--comp` preservado por defaults de flags nuevos.
- Sin cambios de schema destructivos: `proyectos` es aditiva en `studio_config.json`.

## Dependencias

- `studio_config.json` (`bases_por_so`; `proyectos` nueva clave).
- `ffprobe` disponible en los workers de render.
- Nuke stub en `tests/conftest.py` para tests sin Nuke.
- Evidencia precedente: spec `render-config-central` (delta MODIFIED del requirement de "dominio fijo"), `skills/render-red`.

## Plan de Tests (strict TDD)

- Unit (stub, sin Nuke): `mejor_version_comp` mtime pese a V-number menor (test RED primero); resolución layout por proyecto (EP_07 vs PFC_SC13 vs IPYD 104, fechas `-2`); plate más reciente gana; comparación fps/res/frames Root vs plate; ffprobe parseado de fixture.
- Decisiones: falso positivo mtime, naming roto (solo duración/abortar), fps (forzar/cancelar), fuerza `--force-qc`.
- `test_no_fuga`: layouts en código sin IPs/`user@host`/rutas absolutas (patrón relativo).
- Suite completa verde: `python3 -m pytest`.

## Tamaño Estimado

Código fuente 300–450 líneas + tests 200–300 → **~550–750 líneas totales**; sobre el presupuesto de 400 → `sdd-tasks` debe forecastear y recomendar PRs encadenados.

## Criterios de Éxito

- [ ] Selección por mtime elige el .nk más reciente aunque su `_V` sea menor (test).
- [ ] `--proyecto PCF` resuelve `PFC_SC13_010` y `--proyecto IPYD` resuelve `20260628-2` como fecha más reciente (test).
- [ ] Gate aborta con comp a 24fps y plate 23.976 sin `--force-qc`; procede con él (test).
- [ ] Report QC avisa drift preview EP_108 (1558 vs 1665) sin abortar.
- [ ] `test_no_fuga.py` verde (cero IPs/rutas reales en código).
- [ ] Flujo legacy `--comp` sin regresiones; suite verde.
- [ ] `skills/render-red/SKILL.md` documenta el flujo agente y los layouts de los 3 proyectos.

## Proposal Question Round (auto mode; supuestos a revisar)

1. **Operatividad IPYD/PCF**: ¿tipos de render completos en v1 o solo selección/QC de su layout? → Supuesto: operativos si su layout resuelve; el gate no los bloquea.
2. **`--force-qc`**: ¿procede pese a discrepancias o solo re-reporta? → Supuesto: procede.
3. **Proyecto por defecto sin `--proyecto`**: → Supuesto: HTLR con mensaje de aviso.