```yaml
schema: gentle-ai.verify-result/v1
evidence_revision: sha256:4753db95d0085527aa7190b33976d9334c603d4ab7adb03f11eea924c26d4ec9
verdict: pass_with_warnings
blockers: 0
critical_findings: 0
requirements: 12/12
scenarios: 37/37
test_command: python3 -m pytest -q
test_exit_code: 0
test_output_hash: sha256:4753db95d0085527aa7190b33976d9334c603d4ab7adb03f11eea924c26d4ec9
build_command: python3 -m py_compile render_distribuido/render_config.py render_distribuido/render_distribuido.py render_distribuido/render_worker.py render_distribuido/layouts.py render_distribuido/plate_qc.py
build_exit_code: 0
build_output_hash: sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

## Verification Report

**Change**: render-agente-qc (2026-09-02)
**Version**: delta specs RC-SS / RC-QC / RC-MN / RC-CN (4 dominios, 12 requirements, 37 scenarios — recontados leyendo los 4 spec.md)
**Mode**: Strict TDD (orchestrator declaró STRICT TDD MODE IS ACTIVE; `openspec/config.yaml testing.strict_tdd: true` — válido)
**Runner**: python3 -m pytest (pytest 9.0.2, Python 3.14.0)
**Re-verification**: corrección del orquestador tras CRITICAL-1 (commits 164973d + bc8ad6f sobre main).

### Completeness
| Metric | Value |
|--------|-------|
| Tasks total | 25 (re-slice PR1a-e materializado en tasks.md) |
| Tasks complete | 25 ([x] en tasks.md, fases 1–4) |
| Tasks incomplete | 0 |

### Build & Tests Execution
**Build**: ✅ Passed — `python3 -m py_compile` sobre los 5 .py touchados (render_config / render_distribuido / render_worker / layouts / plate_qc): exit 0, salida vacía.

**Tests**: ✅ 634 passed (8.48s) — full suite `python3 -m pytest -q`, exit 0, hash `4753db95…`. Batch del cambio (test_layouts+test_seleccion+test_qc_plate+test_multinodo+test_render_distribuido+test_render_config+test_no_fuga): 224 passed (1.01s); con `--cov`: 224 passed (33.47s).

**test_no_fuga**: ✅ 41 passed (1.57s), exit 0 — 0 fugas (hash `27d8690f…`).

**Coverage** (informacional, idéntico al verify previo): layouts.py 90% ✅ · plate_qc.py 92% ✅ · render_config.py 85% ✅ · render_distribuido.py 37% (módulo legacy; slices nuevos cubiertos individualmente) ⚠️ · render_worker.py 51% (knobs Nuke no testeables con stub) ⚠️ · TOTAL 60%.

### CRITICAL-1 (previo) — RESUELTO
Evidencia de resolución (read-only):
- `git ls-files` → `tests/test_layouts.py` presente en el índice de HEAD.
- Commit 164973d: `test(seleccion): separa tests de layouts (re-slice PR1a-e)` añade `tests/test_layouts.py` (+227) y re-slicéa `test_seleccion.py` (−177).
- Commit bc8ad6f: `docs(render): flujo asistido multi-proyecto, QC gate, skill render-red v2 (PR4)` committea docs/openspec/config.yaml/README/SKILL.md.
- `git archive HEAD` (simulación de clone fresco) → incluye `tests/test_layouts.py`, `tests/test_seleccion.py`, `tests/test_no_fuga.py`. **Un clone fresco de HEAD pasa.**
- `git status --porcelain` → vacío (working tree limpio, sin untracked ni modificados).

### Spec Compliance Matrix (37 escenarios; evidencia = test que pasó en esta corrida)
| Req | Escenario | Test | Resultado |
|-----|-----------|------|-----------|
| RC-SS-01 | HTLR episode | test_layouts.py::test_resolver_planos_htlr_episodio | ✅ COMPLIANT |
| RC-SS-01 | Intent path does not exist | test_layouts.py::test_resolver_planos_remapea_intent_inexistente + test_seleccion.py::test_planos_del_proyecto_intent_remapeado | ✅ COMPLIANT |
| RC-SS-01 | PCF sequence | test_layouts.py::test_resolver_planos_pcf_secuencia | ✅ COMPLIANT |
| RC-SS-01 | IPYD episode | test_layouts.py::test_resolver_planos_ipyd_episodio | ✅ COMPLIANT |
| RC-SS-01 | No-fuga layout | test_no_fuga (scan layouts.py) + test_layouts.py::test_layouts_son_relativas_sin_raices_absolutas | ✅ COMPLIANT |
| RC-SS-02 | Newer mtime beats higher V (+ override v015) | test_seleccion.py::test_mejor_version_mtime_gana_pese_a_v_menor + test_use_version_override_elige_v_menor | ✅ COMPLIANT |
| RC-SS-02 | Autosave and temp ignored | test_seleccion.py::test_candidatas_ignoran_autosave_y_temp | ✅ COMPLIANT |
| RC-SS-02 | mtime tie-break | test_seleccion.py::test_mejor_version_empate_de_mtime_resuelve_por_v_mayor | ✅ COMPLIANT |
| RC-SS-03 | Deselect before confirm | test_seleccion.py::test_confirmar_planos_desmarcar_deja_subset (46→43) | ✅ COMPLIANT |
| RC-SS-03 | Resolve-latest skips confirmation | test_seleccion.py::test_confirmar_planos_resolve_latest_sin_prompt | ✅ COMPLIANT |
| RC-SS-03 | No comp found | test_seleccion.py::test_sin_nk_aborta_nombrando_la_carpeta / test_seleccionar_version_sin_nk_aborta_nombrando_carpeta | ✅ COMPLIANT |
| RC-QC-01 | Most recent date wins | test_layouts.py::test_localizar_plate_fecha_mas_reciente_gana | ✅ COMPLIANT |
| RC-QC-01 | Override selects older plate | test_layouts.py::test_localizar_plate_override_elige_fecha_vieja | ✅ COMPLIANT |
| RC-QC-02 | ProRes fixture parse | test_qc_plate.py::test_probar_plate_parsea_fixture_prores_4444 | ✅ COMPLIANT |
| RC-QC-02 | Probe failure | test_qc_plate.py::test_probar_plate_fallo_aborta_nombrando_la_ruta + test_render_distribuido.py::test_gate_qc_probe_fallo_aborta_nombrando_la_ruta | ✅ COMPLIANT |
| RC-QC-03 | FPS mismatch aborts / force proceeds | test_qc_plate.py::test_comparar_fps_24_vs_23976_error + test_resolver_gate_fps_mismatch_aborta_exit_3_con_decision + test_resolver_gate_force_qc_procede | ✅ COMPLIANT |
| RC-QC-03 | Preview drift warns only | test_qc_plate.py::test_comparar_preview_drift_1558_vs_1665_warning + test_resolver_gate_solo_warnings_no_aborta | ✅ COMPLIANT |
| RC-QC-03 | Naming broken | test_qc_plate.py::test_comparar_naming_roto_error + test_resolver_gate_naming_roto_validar_solo_duracion_resuelve | ✅ COMPLIANT |
| RC-QC-03 | Delivery node overwritten | test_qc_plate.py::test_spec_qc_set_reescribe_delivery_a_specs_del_plate + test_multinodo.py::test_aplicar_qc_spec_reescribe_format_fps_y_rango + test_render_distribuido.py::test_gate_qc_con_force_escribe_reporte_y_devuelve_qc_set (stub-level; knobs reales = check manual pendiente → WARNING-3) | ✅ COMPLIANT* |
| RC-QC-04 | Report emitted with force | test_render_distribuido.py::test_gate_qc_con_force_escribe_reporte_y_devuelve_qc_set + test_qc_plate.py::test_reportar_escribe_json_en_test_render | ✅ COMPLIANT |
| RC-QC-04 | Legacy run unaffected | test_render_distribuido.py::test_es_flujo_asistido_legacy_sin_flags_qc + test_gate_habilitado_solo_flujo_asistido_con_probe + test_seleccion.py::test_es_flujo_asistido_legacy_sin_flags_nuevos | ✅ COMPLIANT |
| RC-MN-01 | Nodes discovered by real name + --wnodes | test_multinodo.py::test_scan_write_nodes_descubre_solo_nombres_reales + test_filtrar_wnodes_explicito_selecciona_subset | ✅ COMPLIANT |
| RC-MN-01 | No friendly-name leakage | test_multinodo.py::test_nombres_reales_sin_labels_friendly | ✅ COMPLIANT |
| RC-MN-02 | EXR per-frame policy | test_multinodo.py::test_exr_por_frame_765_faltantes_de_1665 | ✅ COMPLIANT |
| RC-MN-02 | MOV per-file policy | test_multinodo.py::test_mov_por_archivo_ausente_se_programa_entero | ✅ COMPLIANT |
| RC-MN-02 | CALIB/PLAN only on delivery EXR | test_multinodo.py::test_exigir_delivery_exr_ok_con_entrega_en_alcance + test_exigir_delivery_exr_aborta_si_el_filtro_lo_excluye | ✅ COMPLIANT |
| RC-MN-02 | Preview piggyback with use_limit | test_multinodo.py::test_env_piggyback_lleva_rangos_propios_de_los_previews + test_rango_efectivo_nodo_respeta_use_limit + test_render_branch_clips_piggyback_a_su_rango | ✅ COMPLIANT |
| RC-MN-03 | Force sequence conserves specs | test_multinodo.py::test_forzar_template_exr_convierte_mov_a_secuencia_exr + test_forzar_exr_en_reescribe_archivo_unico_a_secuencia_exr | ✅ COMPLIANT |
| RC-CN-02 | Multiple missing keys | test_render_config.py::test_validar_esquema_acumula_todas_las_faltantes + test_obtener_efectiva_un_systemexit_con_todas_las_faltantes | ✅ COMPLIANT |
| RC-CN-02 | Wrong type | test_render_config.py::test_tipo_incorrecto_bases_por_so_lista + test_proyectos_no_dict_es_error_de_tipo | ✅ COMPLIANT |
| RC-CN-02 | Invalid proyectos entry | test_render_config.py::test_proyectos_valor_str_es_error_de_tipo | ✅ COMPLIANT |
| RC-CN-02 | Proyectos absent is valid | test_render_config.py::test_proyectos_ausente_valido_legacy_y_resuelve_vacio | ✅ COMPLIANT |
| RC-CN-05 | Example validates | test_render_config.py::test_ejemplo_del_repo_valida_con_el_cargador (L733: validar_esquema(example) == []) + test_ejemplo_del_repo_carga_como_config_efectiva (L744: carga por el loader estricto sin SystemExit) — ambos PASAN en esta corrida (2 passed, 0.08s). **Corrige al verify previo**: SÍ hay test committeado (el previo lo marcó PARTIAL por error) | ✅ COMPLIANT |
| RC-CN-05 | Sanitized commit | test_no_fuga.py::test_sin_ips_en_archivos_del_batch + test_sin_pares_usuario_host | ✅ COMPLIANT |
| RC-CN-05 | No IPs in public template | test_no_fuga.py::test_plantilla_publica_sin_ips_y_hosts_hostname | ✅ COMPLIANT |
| RC-CN-05 | ACL documented | test_no_fuga.py::test_readme_documenta_acl_d8 | ✅ COMPLIANT |
| RC-CN-05 | Layout data is relative | test_layouts.py::test_layouts_son_relativas_sin_raices_absolutas + test_no_fuga | ✅ COMPLIANT |

**Compliance summary**: 37/37 COMPLIANT, 0 PARTIAL, 0 FAILING, 0 UNTESTED. La nota de frescura de clone del verify previo queda **eliminada** (todos los tests trackeados en HEAD) y el escenario RC-CN-05 "Example validates" sube a COMPLIANT porque el test committeado test_render_config.py::test_ejemplo_del_repo_valida_con_el_cargador existe y pasa (el verify previo lo marcó PARTIAL por error de rastreo).

### Correctness (Static Evidence — spec→código)
Sin cambios respecto al verify previo; los archivos fuente no se tocaron en la corrección (solo tests/docs). Mapeo spec→código íntegro: layouts.py (resolver_planos/mejor_version_comp/localizar_plate), plate_qc.py (probar_plate/comparar/reportar/decision/spec_qc_set), render_distribuido.py (confirmar_planos/gate_qc/plan_nodo/filtrar_wnodes/forzar_template_exr), render_worker.py (scan_write_nodes/aplicar_qc_spec/forzar_exr_en), render_config.py (validar_esquema aditivo con proyectos).

### Coherence (Design D1–D6)
| Decisión | ¿Seguida? | Notas |
|----------|-----------|-------|
| D1 Layout multi-proyecto como DATOS; proyectos aditivo | ✅ Sí | LAYOUTS relativo; validador aditivo; remapeo 2VFX/Capitulo_7→EP_07 |
| D2 Selección por mtime con tie-break + sospechosa | ✅ Sí | analizar_version devuelve {elegida,candidatas,sospechosa}; --use-version resuelve |
| D3 Gate QC pre-render ON en flujo asistido | ✅ Sí | gate_habilitado = asistido + probe; corre tras PROBE antes de EXISTENTES/CALIB |
| D4 Multi-nodo: descubrimiento + política + CALIB/PLAN entrega | ✅ Sí | en_scope→exigir_delivery_exr; env_piggyback; --force-exr |
| D5 Caminos tristes Q&A __DECISION__ + exit 3 + overrides | ✅ Sí | JSON por stdout; auto→exit 3; --validar-solo-duracion/--fps-forzar/--plate-date |
| D6 Reporte JSON TEST_RENDER/qc_*.json + resumen | ✅ Sí | reportar escribe qc_<proyecto>_<ts>.json; contenido D6 exacto |

Sin desviación de diseño que rompa spec.

### TDD Compliance (Strict TDD)
| Check | Resultado | Detalles |
|-------|-----------|----------|
| TDD Evidence reported | ⚠️ | apply-progress (obs 2264/2265) reporta por PR: archivos RED, suite 548→584→634, commits work-unit — pero NO en el formato de tabla "TDD Cycle Evidence" (RED/GREEN/TRIANGULATE/SAFETY NET). Formato, no vacío. WARNING-2 |
| All tasks have tests | ✅ | 25/25 tareas con archivo de test que EXISTE y está TRACKEADO en HEAD |
| RED confirmed (tests exist) | ✅ | test_layouts.py / test_seleccion.py / test_qc_plate.py / test_multinodo.py / test_render_distribuido.py / test_render_config.py / test_no_fuga.py — todos en git ls-files |
| GREEN confirmed (tests pass) | ✅ | 634 passed en ejecución propia (no solo el reporte de apply) |
| Triangulation adequate | ✅ | Múltiples casos con valores distintos por comportamiento (mtime / tie-break / autosave / sospechosa; fps error/match/warning/naming; EXR 765/replace/corruptos; MOV ausente/presente/keep/replace) |
| Safety Net for modified files | ✅ | Suite progresó verde entre PRs (548→584→634) y 634 hoy; 0 fallos |
| Assertion Quality (5f) | ✅ | Sin tautologías, sin ghost loops, sin smoke-only; aserciones de valor reales; mock ratio sano |

**TDD Compliance**: 7/8 checks ✅ (1 ⚠️ de formato del artefacto, sustancia verificable e independientemente confirmada).

### Test Layer Distribution
| Layer | Tests | Files | Tools |
|-------|-------|-------|-------|
| Unit | 634 | 25+ | pytest + nuke stub (conftest) |
| Integration | 0 | 0 | no disponible (config integration.available: false) |
| E2E | 0 | 0 | no disponible (config e2e.available: false) |
| **Total** | **634** | **~26** | |

### Changed File Coverage
| Archivo | Line % | Rating |
|---------|--------|--------|
| render_distribuido/layouts.py | 90% | ✅ Excellent |
| render_distribuido/plate_qc.py | 92% | ✅ Excellent |
| render_distribuido/render_config.py | 85% | ⚠️ Acceptable |
| render_distribuido/render_distribuido.py | 37% | ⚠️ Low (módulo legacy grande; slices del cambio cubiertos individualmente) |
| render_distribuido/render_worker.py | 51% | ⚠️ Low (knobs Nuke no testeables con stub — gap documentado, WARNING-3) |

### Assertion Quality
**Assertion quality**: ✅ All assertions verify real behavior (0 CRITICAL, 0 WARNING en los archivos del cambio; doble definición de _args_cli en test_seleccion.py es solo duplicación inofensiva → SUGGESTION-2)

### Quality Metrics
**Linter**: ➖ Not available (config linter.available: false)
**Type Checker**: ➖ Not available (config type_checker.available: false)
**Build (py_compile)**: ✅ exit 0

### Issues Found
**CRITICAL**
Ninguno. CRITICAL-1 del verify previo (tests/test_layouts.py UNTRACKED + referenciado por test_no_fuga → clone fresco de HEAD fallaba) está **RESUELTO**: committeado en 164973d, `git archive HEAD` contiene los 3 archivos de test, working tree limpio.

**WARNING**
1. **apply-progress sin tabla formal "TDD Cycle Evidence"** — obs 2264/2265 reportan evidencia TDD por PR (archivos RED, suite 548→584→634, commits) pero no en el formato de columnas RED/GREEN/TRIANGULATE/SAFETY NET del módulo strict. Sustancia verificada independientemente → formato, no vacío. Sin cambios en la corrección.
2. **Knobs reales de reescritura QC_SET no testeables con stub** — aplicar_qc_spec se prueba con fakes (_WriteQcFake/_RootQcFake); el path real (root fps / write format / first-last via Nuke) requiere check manual en worker real. Documentado en design.md Open Questions (L171). Sin cambios; pendiente manual.
3. **openspec/config.yaml counts stale (informacional)** — líneas 55 y 65 dicen "502 passed"; la suite real es 634. Ahora está COMMITTEADO (bc8ad6f tocó config.yaml) pero sigue desactualizado; refrescar (p.ej. en sdd-archive/sdd-init).

**SUGGESTION**
1. **Duplicación _args_cli en test_seleccion.py** (líneas ~66 y ~197, idénticas) — unificar en un solo helper.

**RESUELTOS en la corrección** (ya no figuran como issues): CRITICAL-1 (tests trackeados) y WARNING-5 del verify previo (PR4 + residuo sin commitear: README.md, SKILL.md, config.yaml, openspec/changes/, test_seleccion.py — todo committeado en 164973d + bc8ad6f; árbol limpio).

**CORRECCIÓN al verify previo (SUGGESTION-1 vieja, "Example validates sin test directo")**: REFUTADA por evidencia — `tests/test_render_config.py:733 test_ejemplo_del_repo_valida_con_el_cargador` y `:744 test_ejemplo_del_repo_carga_como_config_efectiva` son tests committeados que cubren el escenario RC-CN-05 y pasan (verificado en esta corrida). El escenario es COMPLIANT; no hace falta test adicional.

### Verdict
**PASS WITH WARNINGS** (envelope `pass_with_warnings`) — CRITICAL-1 RESUELTO y sin blockers nuevos: suite real 634 passed (exit 0), test_no_fuga 41 passed con 0 fugas, 25/25 tareas, **37/37 escenarios compliant** (0 partial — el RC-CN-05 "Example validates" tiene test committeado que pasa), diseño D1–D6 seguido, clone fresco de HEAD verificado vía `git archive` + `git ls-files`. Restan 3 WARNING y 1 SUGGESTION, todos no bloqueantes y preexistentes (W1..W3; W5 resuelto; S1 vieja refutada). Listo para archivar y para push de los commits ya materializados (164973d, bc8ad6f).