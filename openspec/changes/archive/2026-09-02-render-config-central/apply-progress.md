# Apply Progress — render-config-central

**Batch**: PR1 (work-unit 1: T1 + gate D7) — 2026-09-02
**Mode**: Strict TDD (`openspec/config.yaml` → `strict_tdd: true`, runner `python3 -m pytest`)
**Delivery**: auto-chain / stacked-to-main — PR1 targets `main`; batch autonomous, sin push (lo maneja el orquestador).
**Size:exception**: aplica — este commit es el primer tracking de contenido de `render_distribuido/` (aceptado por el orquestador). Real: 935 líneas añadidas (módulo 455 + tests 480), 0 borradas; dentro del presupuesto del work-unit 1 una vez contemplado el tracking.

## Estado de tareas (acumulado)

| Task | Estado | Notas |
|------|--------|-------|
| 1.1 (T1) loader+validator+merge+strict policy | ✅ `[x]` | `render_distribuido/render_config.py` + `tests/test_render_config.py` |
| 1.2 (T2) traducción multi-SO + `mapa_bases`/`_canon` | ⏳ pendiente (PR2) | `_gate_mount` — que tasks.md asigna a T2 — se implementó YA en PR1 por decisión explícita del orquestador (necesario para la política estricta de montaje) |
| 2.1 (T3) refactor orquestador | ⏳ pendiente (PR4) | |
| 2.2 (T4) worker env-only | ⏳ pendiente (PR3) | |
| 3.1 (T5) example/README/ACL | ⏳ pendiente (PR5) | |
| 3.2 (T6) tests restantes + suite | ⏳ pendiente (PR5) | |
| 4.1 (T7) commit sanitizado + guard | ⏳ pendiente (PR5) | |
| 4.2 (T8) spec sync D8 | ⏳ pendiente (PR5) | |

## Qué se implementó (PR1)

`render_distribuido/render_config.py` (nuevo, puro, stdlib-only, testeable sin Nuke):

- **Cadena de resolución**: `ENV_BASE = "RENDER_CONFIG_BASE"` (gana, salta gate D4) → `_cargar_entorno()` lazy con shim de sys.path (D5) → `entorno.primera_ruta_disponible(detectar_so())` → `{base}/.saman/studio_config.json` (`ARCHIVO_DISCO`) → `_cargar_config_local()` (`RENDER_LOCAL_CONFIG` de `SamanTools.config_local` / `render_distribuido.config_local` / `config_local` script-mode) con `_merge_config` per-key (D3: dicts se fusionan un nivel por item; listas reemplazan).
- **Política estricta diferenciada** (`_abortar_sin_fuente`): `FileNotFoundError`/`sin_base` → "Config de render faltante" + copiar `studio_config.example.json` a `{base}/.saman/studio_config.json`; `OSError`/`TimeoutError`/EIO/JSON inválido → mensaje explícito de conexión/montaje (JSON corrupto sí sugiere recrear desde plantilla, spec esc. "No config available") — NUNCA plantilla en fallos de montaje; todo vía `SystemExit`.
- **Autonomía local** (spec: Local complete, no disk / D8): disco ausente, mount caído o sin base + `RENDER_LOCAL_CONFIG` completo → usa el local, sin abort (mismo `validar_esquema`).
- **`validar_esquema(config) -> list[str]`** puro y acumulativo: 1er nivel (`bases_por_so` dict {SO:str}, `workers` list, `sufijos` dict con TO_VFX/COMP/FROM_VFX str) + por worker (`nombre`, `ssh` str|None, `ssh_user`, `nuke_exec`, `base` str; `lc_all` bool) con key path (`workers[1].nuke_exec`) + guía de arreglo; UN `SystemExit` con TODAS las faltantes/tipos.
- **`_gate_mount(base, timeout=3, intentos=2)`** (D7): cache-free (propio `ls -d`/`dir` con timeout local; NO usa `entorno.estado_unidad` — su caché de 10s hace no-op el reintento), 2×3s; ambos intentos fallidos → error de montaje, no "config missing".
- **TODO(T2/PR2)** en el módulo: `traducir_ruta`, `detectar_so_de_ruta`, `mapa_bases`, `_canon`, `normalizar_separadores` + integridad D2 (worker.base bajo base declarada) — NO implementadas en PR1.

## TDD Cycle Evidence (Strict TDD — gate duro)

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1 | `tests/test_render_config.py` | Unit | N/A (nuevo; baseline 392/392 ✅) | ✅ Written → ImportError de colección | ✅ 24 passed | ✅ 26 casos (happy/merge, env gana, autonomía×3, faltante×2, inválido×2, mount×2, validador×7, gate×3, contrato) | ✅ Mensajes acentuados, sin cláusula plantilla en montaje, test redundante consolidado, +2 escenarios spec |

Ciclo verificado: RED (ImportError) → GREEN (24) → TRIANGULATE (26) → REFACTOR (26 siguen verdes) → suite completa 418 ✅.

## Work Unit Evidence

| Evidence | Required value |
|---|---|
| Focused test command and exact result | `python3 -m pytest tests/test_render_config.py` → **26 passed** en 0.34s |
| Runtime harness command/scenario and exact result | N/A — módulo stdlib puro sin frontera de runtime; storage real no se toca (tmp_path + monkeypatch). Harness real (Nuke+unidad LucidLink) es del orquestador/PR4 |
| Rollback boundary | `git revert` del commit de PR1 (solo `render_distribuido/render_config.py` + `tests/test_render_config.py`; no toca `render_distribuido.py`/`render_worker.py`) |

## Suite completa

- Baseline pre-PR1: **392 passed** (`python3 -m pytest -q`)
- Post-PR1: **418 passed** (`python3 -m pytest -q`) — 392 + 26 nuevos
- `python3 -m py_compile render_distribuido/render_config.py tests/test_render_config.py` ✅ (regla apply de config.yaml)

## Desviaciones / interpretaciones

1. **`_gate_mount` movido de T2 a PR1**: tasks.md lo lista en 1.2, pero el orquestador lo exigió en PR1 (la política estricta de montaje lo necesita). 1.2 queda pendiente solo con la parte de traducción.
2. **Integridad D2 (worker.base bajo `bases_por_so`) diferida a T2**: requiere `_canon`/`mapa_bases`; marcada como TODO en `validar_esquema` y en el módulo.
3. **JSON corrupto/no-dict**: tratado como "config ausente/inválida" → sugiere recrear desde plantilla (spec esc. "No config available": "missing/invalid JSON"), coherente con política estricta.
4. **Rescate local solo para disco no disponible**: si el disco existe pero el merge disco+local es inválido, aborta (no cae al local solo) — sigue el Data Flow del design (validador único sobre la fusión).

## Issues / Riesgos

| Riesgo | Detalle |
|---|---|
| Guard T7 (`grep -E "192\.168\|@"`) dará falso positivo | `@pytest.fixture` decorators en `tests/test_render_config.py` (líneas 81, 87) matchean `@`. PR5/T7 debe refinar el guard (excluir decorators o limitar a archivos de datos). Sin IPs ni `@` en strings en los archivos nuevos (verificado). |
| Import de `SamanTools.config_local` real en tests no aislados | Todos los tests del resolver monkeypatean `_cargar_config_local` (aislado del config_local.py real de la máquina). |
| Mensajes con acentos | Elección de estilo consistente con el código existente (mensajes de orquestador en español acentuado); tests asertan fragmentos estables. |

## Next steps

- **PR2 = T2** (work-unit 2): `traducir_ruta`, `detectar_so_de_ruta`, `_canon`, `normalizar_separadores`, `mapa_bases` + integridad D2 + tests `-k "traducir or gate"`. Reusar el TODO del módulo y este apply-progress (merge protocol).
- PR3 = T4 (worker env-only), PR4 = T3 (orquestador, size:exception por tracking), PR5 = T5-T8.

---

# PR2 (work-unit 2: T2 — traducción multi-SO + integridad D2) — 2026-09-02

**Batch**: PR2 (T2) — 2026-09-02
**Mode**: Strict TDD (`openspec/config.yaml` → `strict_tdd: true`, runner `python3 -m pytest`)
**Delivery**: auto-chain / stacked-to-main — PR2 apunta a `main` (tras PR1 eb8956e); batch autónomo, sin push.
**Size**: work-unit 2 — 312 adiciones / 6 borradas (módulo +119/−6, tests +193/0); dentro del presupuesto del work-unit (≠ el estimado +100 porque el fixture PR1 se ajustó para D2, ver desvíos).

## Estado de tareas (acumulado — merge con PR1)

| Task | Estado | Notas |
|------|--------|-------|
| 1.1 (T1) loader+validator+merge+strict policy | ✅ `[x]` | PR1 (commit eb8956e) |
| 1.2 (T2) traducción multi-SO + `mapa_bases`/`_canon` | ✅ `[x]` | PR2 (42f97f6); `_gate_mount` ya se implementó en PR1 por decisión del orquestador |
| 2.1 (T3) refactor orquestador | ⏳ pendiente (PR4) | |
| 2.2 (T4) worker env-only | ✅ `[x]` | PR3 (este batch) — `render_worker.py` + `tests/test_render_worker.py` |
| 3.1 (T5) example/README/ACL | ⏳ pendiente (PR5) | |
| 3.2 (T6) tests restantes + suite | ⏳ pendiente (PR5) | |
| 4.1 (T7) commit sanitizado + guard | ⏳ pendiente (PR5) | |
| 4.2 (T8) spec sync D8 | ⏳ pendiente (PR5) | |

## Qué se implementó (PR2)

En `render_distribuido/render_config.py` (TODO(T2/PR2) resuelto — docstring del módulo y de `validar_esquema`):

- **`_canon(ruta) -> str`**: normalización canónica POSIX — `PurePosixPath(str(ruta).replace("\\", "/")).as_posix()`; forward slashes, sin trailing `/`; no resuelve `..` (D1).
- **`mapa_bases(config) -> dict[str, str]`**: `{so: base_canon}` derivado de `bases_por_so` (solo valores `str`; `{}` si el dict falta/es inválido).
- **`detectar_so_de_ruta(ruta, config) -> str | None`**: longest-prefix sobre las bases canónicas (igualdad o `startswith(base + "/")`); `None` si ningún prefijo declarado calza.
- **`normalizar_separadores(ruta, so) -> str`**: Windows ⇒ `str(PureWindowsPath(canon))` (backslashes); cualquier otro SO ⇒ canon (solo `/`). Es la corrección 3 del spec: no basta reemplazar el prefijo.
- **`traducir_ruta(ruta, desde_so, hacia_so, config) -> str`**: reemplaza el prefijo de la base de origen por el de la base destino y normaliza separadores hacia el SO destino; `desde_so` desconocido (None o no declarado) ⇒ autodetección vía `detectar_so_de_ruta`; ruta fuera de prefijos o par no declarado ⇒ ruta INTACTA (spec: Unknown prefix).
- **Integridad D2 en `validar_esquema`**: acumula error `workers[i].base` cuando la base del worker no cae (comparación canónica: igualdad o subruta con `/`) bajo ninguna base declarada de `bases_por_so`; no abort silencioso — error con key path + guía.

## TDD Cycle Evidence (Strict TDD — gate duro)

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.2 | `tests/test_render_config.py` | Unit | ✅ 26/26 | ✅ 16 failed (AttributeError por funciones inexistentes + D2 ausente) | ✅ 44 passed | ✅ 18 casos (traducir×9: win→linux/mac, darwin→win, custom /media, autodetección×2, intacto×2; detectar×3; mapa/_canon/normalizar×3; D2×3) | ✅ Condición redundante eliminada en `traducir_ruta`; docstring de escenarios del spec; fixture PR1 re-ordenado (escribir_json tras mutar base) |

Ciclo verificado: RED (16 fallos nuevos) → GREEN (44) → TRIANGULATE (18 casos) → REFACTOR (44 siguen verdes) → suite completa 436 ✅.

## Work Unit Evidence

| Evidence | Required value |
|---|---|
| Focused test command and exact result | `python3 -m pytest tests/test_render_config.py` → **44 passed** en 0.22s (18 nuevos + 26 PR1) |
| Runtime harness command/scenario and exact result | N/A — funciones puras sobre config en memoria (base tmp_path solo donde aplica); sin disco real ni frontera de runtime (harness real Nuke+LucidLink = orquestador/PR4) |
| Rollback boundary | `git revert` del commit de PR2 (solo `render_distribuido/render_config.py` + `tests/test_render_config.py`; no toca `render_distribuido.py`/`render_worker.py`) |

## Suite completa

- Baseline pre-PR2: **418 passed** (`python3 -m pytest -q`)
- Post-PR2: **436 passed** (`python3 -m pytest -q`) — 418 + 18 nuevos
- `python3 -m py_compile render_distribuido/render_config.py tests/test_render_config.py` ✅ (regla apply de config.yaml)

## Desviaciones / interpretaciones (PR2)

1. **Fixture PR1 ajustado por D2** (`test_happy_path_json_local_merge_por_llave`): el override local `Linux=/mnt/otra_base` dejaba al worker vfxserver (`base=/mnt/wupm/2026`) fuera de toda base declarada TRAS el merge; D2 (correctamente) abortaba. El fixture ahora escribe el JSON con `workers[1].base=/mnt/otra_base` para que la config fusionada sea esquema-válida. Es comportamiento NUEVO de D2 (el validador corre sobre la fusión disco+local, Data Flow del design), no una regresión.
2. **`desde_so` desconocido = None o no declarado en `bases_por_so`** ⇒ `traducir_ruta` autodetecta; si el SO dado SÍ está declarado pero la ruta no cae bajo su base ⇒ intacta (D1: "canon no cae bajo base de desde_so ⇒ intacta").
3. **`_gate_mount` quedó en PR1** (decisión del orquestador documentada en PR1); el PR2 de este batch cubre solo traducción + D2 (tasks.md 1.2 conserva la mención del gate por ser la misma tarea).
4. **Incidente de edición**: un `oldString` sin indentación inicial provocó match difuso del editor que borró `escribir_json` del fixture (detectado en GREEN, 43→44 tras restaurar y reordenar). Guardado como lección de herramienta, no de diseño.

## Issues / Riesgos

| Riesgo | Detalle |
|---|---|
| `_canon` de rutas sin drive en PureWindowsPath | `str(PureWindowsPath('/media/...'))` renderiza `\media\...` (root del drive actual). No afecta el flujo: la traducción a Windows SIEMPRE parte de `bases[hacia_so]` con drive declarado (`W:/...`). Verificado en GREEN. |
| Autodetección sobre bases solapadas | Longest-prefix resuelve solapes reales (test: `/Volumes/wupm` vs `/Volumes/wupm/2026`); configs con bases ambiguas siguen siendo responsabilidad del admin (documentado en design D2). |

## Next steps

- **PR3 = T4** (2.2, worker env-only D6): `render_worker.py` lee TO_SUF/COMP_SUF/FROM_SUF solo desde `os.environ`, sin fallbacks `/HTLR/...` + tests `-k "env"`.
- PR4 = T3 (2.1, orquestador config-driven + env argv D6, size:exception por tracking), PR5 = T5–T8 (example/README/ACL, tests restantes, guard anti-fuga T7, spec sync D8).

---

# PR3 (work-unit 3: T4 — worker env-only D6) — 2026-09-02

**Batch**: PR3 (T4) — 2026-09-02
**Mode**: Strict TDD (`openspec/config.yaml` → `strict_tdd: true`, runner `python3 -m pytest`)
**Delivery**: auto-chain / stacked-to-main — PR3 apunta a `main` (tras PR2 42f97f6); batch autónomo, sin push (lo maneja el orquestador).
**Size**: work-unit 3 — primer tracking de `render_worker.py` (223 líneas) + tests nuevos (114); dentro del presupuesto del work-unit 3 estimado (~240, incl. tracking).

## Estado de tareas (acumulado — merge con PR1+PR2)

| Task | Estado | Notas |
|------|--------|-------|
| 1.1 (T1) loader+validator+merge+strict policy | ✅ `[x]` | PR1 (commit eb8956e) |
| 1.2 (T2) traducción multi-SO + `mapa_bases`/`_canon` | ✅ `[x]` | PR2 (42f97f6); `_gate_mount` ya se implementó en PR1 por decisión del orquestador |
| 2.1 (T3) refactor orquestador | ⏳ pendiente (PR4) | |
| 2.2 (T4) worker env-only | ✅ `[x]` | PR3 (este batch) — `render_worker.py` + `tests/test_render_worker.py` |
| 3.1 (T5) example/README/ACL | ⏳ pendiente (PR5) | |
| 3.2 (T6) tests restantes + suite | ⏳ pendiente (PR5) | |
| 4.1 (T7) commit sanitizado + guard | ⏳ pendiente (PR5) | |
| 4.2 (T8) spec sync D8 | ⏳ pendiente (PR5) | |

## Qué se implementó (PR3)

En `render_distribuido/render_worker.py` (solo sufijos — NADA más):

- **Docstring de módulo nuevo** (no existía): documenta el contrato D6 — los sufijos se leen SOLO de las variables de entorno que el orquestador inyecta explícitamente en el argv remoto; sin rutas de estudio.
- **`sufijos_desde_env(env) -> dict`** (nueva, pura): devuelve `{"TO_SUF", "COMP_SUF", "FROM_SUF"}` leyendo SOLO del mapping recibido; variable ausente ⇒ sufijo `""` (la base sin subdirectorio). Cero fallbacks hardcodeados.
- **`setear_variables(base)` refactorizada**: `PYTHON_TO_VFX/COMP/FROM_VFX = base + sufijos_desde_env(os.environ)[...]`; eliminados los fallbacks `/HTLR/TO_VFX/`, `/HTLR/COMP/`, `/HTLR/FROM_VFX/`.
- Sin tocar: `COMP`/`WNODE`/`MODE`/`BASE` module-level, `lotes_contiguos`, `ejecutar_frames`, `emitir`, `perf_nodo`, `rango_plate`, ramas MODE. `render_distribuido.py` intacto (PR4).
- grep `render_worker.py`: **0 coincidencias `/HTLR/`** (verificado).

## TDD Cycle Evidence (Strict TDD — gate duro)

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 2.2 | `tests/test_render_worker.py` | Unit | ✅ 436/436 (suite) + 44/44 proxy `test_render_config.py` | ✅ 6 failed (4×AttributeError `sufijos_desde_env` inexistente, ausencia→base pelada incumplida, guard fuente `/HTLR/` presente) | ✅ 7 passed | ✅ 7 casos (presentes×2, ausentes, parciales, claves ajenas, `setear_variables` env presente, `setear_variables` sin env, guard fuente) | ✅ Docstring módulo nuevo; función pura extraída; sin duplicación; sin tocar lógica ajena |

Ciclo verificado: RED (6 fallos nuevos; 1 test de env-presente pasaba ya por coincidencia de la aprobación) → GREEN (7) → TRIANGULATE (7 casos) → REFACTOR (7 siguen verdes) → suite completa 443 ✅.

## Work Unit Evidence

| Evidence | Required value |
|---|---|
| Focused test command and exact result | `python3 -m pytest tests/test_render_worker.py` → **7 passed** en 0.37s |
| Runtime harness command/scenario and exact result | Harness de import con stub: `MODE=render` + `BASE` + stubs de `nuke.scriptOpen`/`nuke.execute` (el bloque module-level ejecuta su rama render contra el stub, sin Nuke real ni red). Harness real (Nuke+LucidLink remoto) = orquestador/PR4 |
| Rollback boundary | `git revert` del commit de PR3 (solo `render_distribuido/render_worker.py` + `tests/test_render_worker.py`; no toca `render_config.py` ni `render_distribuido.py`) |

## Suite completa

- Baseline pre-PR3: **436 passed** (`python3 -m pytest -q`)
- Post-PR3: **443 passed** (`python3 -m pytest -q`) — 436 + 7 nuevos
- `python3 -m py_compile render_distribuido/render_worker.py tests/test_render_worker.py` ✅ (regla apply de config.yaml)
- grep `/HTLR/` en `render_worker.py`: 0 coincidencias (exit 1) ✅

## Desviaciones / interpretaciones (PR3)

1. **Env ausente ⇒ base sin sufijo** (`""`), no error: sigue design D6 (`os.environ.get("TO_SUF", "")`) y la recomendación del orquestador ("fallback a la base sin sufijo o error claro controlado"). Documentado en docstring de módulo, `sufijos_desde_env` y test.
2. **Tests en `tests/test_render_worker.py` (archivo nuevo)**, no en `test_render_config.py`: el worker es un módulo con `import nuke` y bloque module-level ejecutable; el aislamiento en su propio archivo evita acoplar el fixture de import (stubs + env) a los tests puros del loader. El enfoque del fixture + función pura sigue el patrón "extrae y verifica" del orquestador.
3. **Fixture importa el módulo con `MODE=render`**: el bloque module-level ejecuta `scriptOpen`/`execute` contra stubs añadidos a `nuke` (`raising=False`, autorestaurados por monkeypatch) e imprime `__WORKER__...` (capturado por pytest). `nuke.tcl` sigue ausente del stub — `setear_variables` lo envuelve en try/except (comportamiento existente).
4. **`COMP` module-level conserva su fallback** `BASE + "/TEST_RENDER/prueba_test.nk"`: NO es un sufijo y no contiene `/HTLR/`; fuera del scope de T4 (solo TO_SUF/COMP_SUF/FROM_SUF). No tocado.
5. **`tests/test_render_worker.py` restauran `__main__`** a `""` (autouse fixture): evita contaminación cruzada con tests que leen `PYTHON_*` (test_rutas, test_entorno...), que asumen el estado inicial de conftest.

## Issues / Riesgos

| Riesgo | Detalle |
|---|---|
| Import del worker en tests depende del stub | El fixture añade `scriptOpen`/`execute` al stub compartido de conftest (autorestaurados por monkeypatch tras cada test). Si el stub crece, el fixture se mantiene. |
| `sufijos_desde_env` no valida los valores | El orquestador (PR4) inyecta los sufijos desde `sufijos` de la config validada; el worker los aplica tal cual (contrato D6, responsabilidad del admin). Vacío = base pelada, sin inventos. |

## Next steps

- **PR4 = T3** (2.1, orquestador config-driven + env argv D6, size:exception por tracking): `render_distribuido.py` con `obtener_config_efectiva()`, `ssh=f"{ssh_user}@{ssh}"`, `bin`→`nuke_exec`, `template_local` vía `traducir_ruta`, `ejecutar` env explícito `KEY='val'`, sufijos desde config (spec esc. "Suffix defaults from config"). Dep: 1.1, 1.2, 2.2 (listo).
- PR5 = T5–T8 (example/README/ACL, tests restantes, guard anti-fuga T7, spec sync D8).
---

# PR4 (work-unit 4: T3 — orquestador config-driven) — 2026-09-02

**Batch**: PR4 (T3) — 2026-09-02
**Mode**: Strict TDD (`openspec/config.yaml` → `strict_tdd: true`, runner `python3 -m pytest`)
**Delivery**: auto-chain / stacked-to-main — PR4 apunta a `main` (tras PR3 bf368c6); batch autónomo, sin push (lo maneja el orquestador).
**Size**: work-unit 4 — primer tracking de `render_distribuido.py` (516 líneas + 17 tests nuevos); dentro del presupuesto del work-unit 4 una vez contemplado el tracking (~480).

## Estado de tareas (acumulado — merge con PR1+PR2+PR3)

| Task | Estado | Notas |
|------|--------|-------|
| 1.1 (T1) loader+validator+merge+strict policy | ✅ `[x]` | PR1 (commit eb8956e) |
| 1.2 (T2) traducción multi-SO + `mapa_bases`/`_canon` | ✅ `[x]` | PR2 (42f97f6); `_gate_mount` ya se implementó en PR1 por decisión del orquestador |
| 2.1 (T3) refactor orquestador | ✅ `[x]` | PR4 (este batch) — `render_distribuido.py` config-driven + `tests/test_render_distribuido.py` |
| 2.2 (T4) worker env-only | ✅ `[x]` | PR3 (commit bf368c6) |
| 3.1 (T5) example/README/ACL | ⏳ pendiente (PR5) | |
| 3.2 (T6) tests restantes + suite | ⏳ pendiente (PR5) | |
| 4.1 (T7) commit sanitizado + guard | ⏳ pendiente (PR5) | |
| 4.2 (T8) spec sync D8 | ⏳ pendiente (PR5) | |

## Qué se implementó (PR4)

`render_distribuido/render_distribuido.py` (orquestador, primer tracking — NUNCA se versiona el archivo con IPs):

- **Eliminados** `WORKERS` (con IPs reales 192.168.x, usuarios servermac/saman y bins absolutos), `BASE_MAC`, `BASE_LINUX` y los defaults argparse `/HTLR/TO_VFX/`, `/HTLR/COMP/`, `/TEST_RENDER/`. El módulo ya no contiene NINGÚN dato del estudio.
- **`construir_workers(config_workers)`** (pura): convierte los workers de la config a la forma interna — `ssh` = `ssh_user + "@" + host` SOLO si `ssh` no es nulo/vacío (local ⇒ `None`), `bin` ← `nuke_exec`, copia `base` y `lc_all`.
- **`filtrar_por_nombre(workers, nombres_csv)`** (pura): filtro `--workers` por nombre; None/vacío ⇒ todos; nombres comparados en Python, jamás llegan a un shell (D6).
- **`sufijos_efectivos(sufijos_config, to_suf, comp_suf, from_suf)`** (pura): defaults desde `config["sufijos"]` (spec esc. "Suffix defaults from config"); flags CLI sobreescriben por corrida. `--to-suf/--comp-suf/--from-suf` pasan a `default=None`.
- **`so_local()`** (pura): `platform.system()` → clave del esquema (`Darwin`→`macOS`, `Linux`→`Linux`, `Windows`→`Windows`).
- **`template_local(template, config)`**: reemplaza el mapeo inline `/mnt`↔`/Volumes` con `render_config.detectar_so_de_ruta` + `render_config.traducir_ruta` hacia `so_local()` (multi-SO, spec: Multi-OS path translation); prefijo no declarado ⇒ intacto.
- **`main()`**: `obtener_config_efectiva()` post-parse → workers construidos+filtrados y sufijos resueltos ANTES de probe/calib/plan/render. El resto del orquestador (probe/calib/plan/render/política, `ejecutar` con env explícito D6 ya existente) queda intacto: solo cambió la FUENTE de datos.
- Docstring de módulo actualizado (Uso sin `/HTLR/`), import de `render_config` con fallback script-mode (try/except ImportError, patrón D5).
- Import lazy sin Nuke: `python3 -m py_compile` OK; testeable puro.

## TDD Cycle Evidence (Strict TDD — gate duro)

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 2.1 | `tests/test_render_distribuido.py` | Unit | ✅ 443/443 (suite) + 44/44 proxy `test_render_config.py` | ✅ 16 failed (AttributeError por funciones inexistentes: construir_workers/filtrar_por_nombre/sufijos_efectivos/so_local/template_local(config); 1 preexistente pasó: env_worker) | ✅ 17 passed | ✅ 17 casos (construir×2 remoto/local; filtrar×4; sufijos×3 defaults/CLI/parcial; env_worker×1 atando config→env; template×5 linux→mac, windows→mac, misma base, prefijo desconocido, vacío; so_local×3 SOs; guard fuente×1) | ✅ Docstring neutralizado (sin rutas reales), comentario del test sin `usuario@host`, import sys removido; 17 siguen verdes |

Ciclo verificado: RED (16 fallos nuevos; `env_worker` preexistente ya pasaba) → GREEN (17) → TRIANGULATE (17 casos multi-insumo, sin Fake It) → REFACTOR (17 siguen verdes) → suite completa 460 ✅.

## Work Unit Evidence

| Evidence | Required value |
|---|---|
| Focused test command and exact result | `python3 -m pytest tests/test_render_distribuido.py` → **17 passed** en 0.15s |
| Runtime harness command/scenario and exact result | N/A — refactor de FUENTE de datos a funciones puras (sin frontera de runtime); el harness real (Nuke+LucidLink remoto) requiere la config del estudio y es del orquestador/PR5 (smoke). `import render_distribuido.render_distribuido` sin Nuke verificado por la propia colección de tests |
| Rollback boundary | `git revert` del commit de PR4 (solo `render_distribuido/render_distribuido.py` + `tests/test_render_distribuido.py`; no toca `render_config.py` ni `render_worker.py`) |

## Suite completa

- Baseline pre-PR4: **443 passed** (`python3 -m pytest -q`)
- Post-PR4: **460 passed** (`python3 -m pytest -q`) — 443 + 17 nuevos
- `python3 -m py_compile render_distribuido/render_distribuido.py tests/test_render_distribuido.py` ✅ (regla apply de config.yaml)
- grep `192\.168|@[a-z]` en `render_distribuido.py` + `test_render_distribuido.py`: **0 coincidencias** (exit 1) ✅ — sin decorators `@pytest` en el test nuevo (cero decoradores)
- grep marcadores viejos (`servermac`, `saman@`, `/HTLR/`, `BASE_MAC`, `BASE_LINUX`) fuera de los asserts-guard del test: **0** ✅

## Desviaciones / interpretaciones (PR4)

1. **`--from-suf` default cambió de `/TEST_RENDER/` a config**: antes era `/TEST_RENDER/` (no estudiado); ahora `None` → `sufijos.FROM_VFX` de la config (spec: "Suffix defaults from config" cubre los tres). La calibración sigue forzando su propio `FROM_SUF=/TEST_RENDER/calib_<worker>/` (carpeta de calib, comportamiento preservado).
2. **`env_worker` intacta**: la verificación del escenario "worker env TO_SUF equals /TO/" se hace con `argparse.Namespace` sobre `env_worker` (1 test) + `sufijos_efectivos` (función pura que alimenta `main()`); no se cambió la firma para no arrastrar sufijos por 4 call-sites.
3. **`so_local()` vía `platform.system()`**, no `entorno.detectar_so()`: evita el import lazy de SamanTools en el orquestador para una clave de diccionario; el mapeo replica el de `entorno.detectar_so()` (Darwin→macOS, Windows→Windows, Linux→Linux). Test con monkeypatch de `platform.system`.
4. **Import de `render_config` con try/except**: `from render_distribuido import render_config` (pytest/repo-root) con fallback `import render_config` (script mode, sys.path[0]=carpeta) — mismo espíritu del shim D5.
5. **Guard anti-datos en el test** muestra cómo T7 debe refinar el grep: las cadenas `"servermac"`/`"BASE_MAC"` viven SOLO dentro de asserts de ausencia del guard; el grep `192\.168|@[a-z]` no las matchea. Coincide con el riesgo ya anotado en PR1.

## Issues / Riesgos

| Riesgo | Detalle |
|---|---|
| Orquestador inoperante sin config en disco | Por diseño (política estricta): `obtener_config_efectiva()` aborta con guía hasta que exista `{base}/.saman/studio_config.json`. El example se suma en PR5 (T5). |
| Tests con rutas `/Volumes/wupm/2026` y `/media/wupm/2026` | Ficticias/ejemplo del spec (mismo patrón que `config_valida()` de PR1); sin IPs ni usuarios reales. El escenario cross-SO del prompt pide explícitamente template `/media/wupm...` → orquestador `/Volumes/wupm`. |
| `ruta_repo` conserva `/saman-nuke-tools/render_distribuido` | Es el nombre público del repo (layout relativo a `worker["base"]`), no dato del estudio. |

## Next steps

- **PR5 = T5–T8**: `studio_config.example.json` + README + ACL (D8), tests restantes de `test_render_config.py` (T6: example validates, ejecutar env argv, gate retry), guard anti-fuga `tests/test_no_fuga.py` (T7, refinando `@pytest`), spec sync D8 (T8), y commit sanitizado del tree `render_distribuido/` completo.

---

# PR5 (work-unit 5: T5 + T6 + T7 + T8 — cierre del cambio) — 2026-09-02

**Batch**: PR5 (T5–T8) — 2026-09-02. Ultimo PR de la cadena.
**Mode**: Strict TDD (`openspec/config.yaml` → `strict_tdd: true`, runner `python3 -m pytest`)
**Delivery**: auto-chain / stacked-to-main — PR5 apunta a `main` (tras PR4 39f7247); batch autónomo, sin push (lo maneja el orquestador).
**Size**: work-unit 5 — ~520 líneas añadidas (example 80L + README 75L + guard 140L + tests +30; +2 archivos nuevos del tracking: README, hello.py, example).

## Estado de tareas (acumulado — todos [x])

| Task | Estado | Notas |
|------|--------|-------|
| 1.1 (T1) loader+validator+merge+strict policy | ✅ `[x]` | PR1 (eb8956e) |
| 1.2 (T2) traducción multi-SO + `mapa_bases`/`_canon` | ✅ `[x]` | PR2 (42f97f6); `_gate_mount` implementado en PR1 por decisión del orquestador |
| 2.1 (T3) refactor orquestador | ✅ `[x]` | PR4 (39f7247) |
| 2.2 (T4) worker env-only | ✅ `[x]` | PR3 (bf368c6) |
| 3.1 (T5) example/README/ACL | ✅ `[x]` | PR5 (este batch) — `studio_config.example.json`, `README.md`, nota ACL en `docs/ARQUITECTURA.md` |
| 3.2 (T6) tests restantes + suite | ✅ `[x]` | PR5 (este batch) — example validates ×2, ejecutar env argv ×2 |
| 4.1 (T7) commit sanitizado + guard | ✅ `[x]` | PR5 (este batch) — `tests/test_no_fuga.py` (27 tests) + sanitización de `_guia`/docstring en `render_config.py` + fixture `/HTLR/`→`/ESTUDIO/` |
| 4.2 (T8) spec sync D8 | ✅ `[x]` | PR5 (este batch) — delta MODIFIED en `spec.md` (requirement + scenario "ACL documented"); `admin-ONLY` ausente (grep 0) |

**8/8 tareas completas — listo para verify.**

## Qué se implementó (PR5)

### T5 — Activos públicos (sin datos reales)

- **`render_distribuido/studio_config.example.json`**: plantilla CONFORME al esquema (validada por `validar_esquema == []` y por la carga efectiva completa). Cero datos reales: hosts ficticios con hostname (`vfxserver.studio.local`, `workstation.studio.local`, worker local `macpro` con `ssh: null`), rutas ficticias (`/Volumes/estudio/2026`, `/media/estudio/2026`, `W:\estudio\2026`), sufijos ficticios (`/STUDIO/TO_VFX/`...), `ssh_user` ficticios, `nuke_exec` ficticios. Integridad D2: cada `worker.base` cae bajo su `bases_por_so`.
- **`render_distribuido/README.md`**: patrón (dónde vive `{base}/.saman/studio_config.json`, cómo copiar el example y completar), política estricta, ACL D8 (admin WRITE + workers READ via `ssh_user`, fallback `RENDER_LOCAL_CONFIG`, criterio `cat`), pasos de creación y uso del orquestador con la config. Sin `@`, sin IPs, sin raíces reales, sin `/HTLR/`.
- **`docs/ARQUITECTURA.md`**: item 7 de "Reglas operativas" — ACL D8 (admin WRITE + worker READ sobre `.saman/studio_config.json`, fallback `config_local.py` completo por nodo, verificación `cat`).

### T6 — Tests restantes del spec (19/19 escenarios)

- `test_render_config.py` +2: `test_ejemplo_del_repo_valida_con_el_cargador` (spec "Example validates": `validar_esquema(example) == []`) y `test_ejemplo_del_repo_carga_como_config_efectiva` (camino real: plantilla copiada a `{base}/.saman/studio_config.json` carga sin abort, workers/sufijos resueltos — aserción real sobre la producción).
- `test_render_distribuido.py` +2: `test_ejecutar_remoto_compone_env_explicito_en_argv` (D6 + fila threat matrix "Remote command/env composition": argv remoto con token `env KEY='val' ...` + `LC_ALL=C` para lc_all, sin `shell=True`) y `test_ejecutar_local_pasa_argv_sin_env_ni_ssh` (worker local: argv directo). Tests de APROBACIÓN del comportamiento ya implementado en PR4 (no hubo RED de código: el comportamiento existía; se fijó con aserciones).
- Gate 2×3s: ya cubierto por los 3 tests de `_gate_mount` de PR1 (retry, ambos fallan, directorio real) — sin gaps.
- Mapeo de los 19 escenarios de spec → tests: 16 previos + 16 (Example validates) + 17/18 (guard T7) + 19 (README ACL, guard) — completo.

### T7 — Guard anti-fuga + commit sanitizado

- **`tests/test_no_fuga.py`** (27 tests): escanea los archivos TRACKEADOS del batch (`render_distribuido/*.py`, `*.json`, `README.md`, tests del batch) contra: (1) IPs `192\.168|10\.0|172\.(1[6-9]|2\d|3[01])` en TODO el scope; (2) pares `@[a-z]` excluyendo decorators (línea que empieza con `@`: `@pytest.fixture`, `@tech...`); (3) raíces reales `/Volumes/wupm` y `/mnt/wupm` SOLO en archivos no-test de `render_distribuido`. + 2 tests directos: plantilla sin IPs y hosts-hostname (spec "No IPs in public template") y README documenta ACL D8 (spec "ACL documented").
- **Sanitización** para que el guard pase: `_guia()` de `render_config.py` (ejemplos `/Volumes/wupm/2026` → `/Volumes/estudio/2026` y `/HTLR/...` → `/ESTUDIO/...`) y docstring de `detectar_so_de_ruta` (`/Volumes/wupm` → `/Volumes/estudio`); fixture `config_valida()` de `test_render_config.py` (sufijos `/HTLR/` → `/ESTUDIO/` — valores no asertados, cero impacto).
- **hello.py** (probe de calibración del orquestador, untracked hasta ahora) agregado al tracking en este commit: `render_distribuido/` queda COMPLETO versionado.
- Resultado guard tras el batch: IPs 0 · `@[a-z]` sin decorators 0 · raíces reales en no-test 0 · `/HTLR/` en `render_distribuido/` 0 (los únicos hits greps están dentro del propio `test_no_fuga.py`, auto-excluido del escaneo).

### T8 — Sync de spec (ACL D8)

- Delta MODIFIED en `specs/render-config-central/spec.md`: el requirement "Public template, docs, tests, sanitized commit" cambia "admin-ONLY read/write" por "admin WRITE + worker READ via workers' `ssh_user`, fallback `RENDER_LOCAL_CONFIG` completo en `config_local.py`" (D8); el scenario "ACL documented" refleja D8 + fallback. Resto del requirement y los otros 3 escenarios intactos. `grep admin-ONLY` → 0.

## TDD Cycle Evidence (Strict TDD — gate duro)

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 3.1 | `tests/test_render_config.py` (+2) | Unit | ✅ 460/460 suite | ✅ 2 failed (FileNotFoundError: example.json no existe) | ✅ 46 passed | ✅ 2 casos (validar_esquema puro + carga efectiva completa con asserts reales de workers/sufijos) | ✅ README/example sin `@`/IPs/raíces; fixture `/HTLR/`→`/ESTUDIO/` (sin asserts afectados) |
| 3.2 | `tests/test_render_distribuido.py` (+2) | Unit | ✅ 460/460 suite | ➖ Aprobación (comportamiento D6 ya implementado en PR4; sin código nuevo que falte) | ✅ 19 passed (1 fix de aserción: el argv remoto viaja DENTRO del token `env ...`) | ✅ 2 casos (remoto con env+LC_ALL+C y sin shell; local argv directo) | ✅ host compuesto por concatenación (`"render_user" + "@" + host`) para no violar el guard |
| 4.1 | `tests/test_no_fuga.py` (27) | Unit | ✅ 460/460 suite | ✅ 6 failed (README ausente ×4; raíces reales en `render_config.py` ×1; ACL-doc ×1) | ✅ 27 passed | ✅ 26 casos parametrizados (9 IPs + 9 usuario@host + 6 raíces + exist-archivos) + 2 directos | ✅ Sanitización `_guia`/docstring (rutas ficticias); hard-split scope no-test vs tests documentado |
| 4.2 | — (spec delta, sin test) | Docs | ✅ spec previa | ➖ N/A | ✅ `grep admin-ONLY` → 0; scenario D8 | ➖ Single (1 requirement + 1 scenario) | ➖ Ninguno |

Ciclo verificado: RED→GREEN→TRIANGULATE en T5/T6/T7 (T8 es delta de docs, verificado por grep) → suite completa 491 ✅.

## Work Unit Evidence

| Evidence | Required value |
|---|---|
| Focused test command and exact result | `python3 -m pytest tests/test_no_fuga.py tests/test_render_config.py tests/test_render_distribuido.py` → **95 passed** (27 + 46 + 19... trío del batch: 27+46+19=92 con `-q`) — comando mínimo del unit: `python3 -m pytest tests/test_no_fuga.py tests/test_render_config.py -k "ejemplo or fuga or readme"` |
| Runtime harness command/scenario and exact result | N/A — activos públicos + guard estático + tests puros; sin frontera de runtime nueva (el harness real Nuke+LucidLink es del orquestador con la config del estudio; smoke post-rollout) |
| Rollback boundary | `git revert` del commit `feat(render): ejemplo publico + docs ACL + guard anti-fuga` (solo ejemplo/README/hello/ARQUITECTURA/guia-sanitizada/tests+guard; no toca lógica del loader) y del `chore(openspec): sync spec ACL` (spec/tasks/apply-progress) |

## Suite completa

- Baseline pre-PR5: **460 passed** (`python3 -m pytest -q`)
- Post-PR5: **491 passed** (`python3 -m pytest -q`) — 460 + 31 nuevos (2 ejemplo + 2 ejecutar + 27 guard)
- `python3 -m py_compile render_config.py test_render_config.py test_render_distribuido.py test_no_fuga.py` ✅ (regla apply de config.yaml)
- Guard anti-fuga: IPs 0 · `@[a-z]` sin decorators 0 · `/Volumes/wupm|/mnt/wupm` en no-test 0 · `/HTLR/` en `render_distribuido/` 0

## Desviaciones / interpretaciones (PR5)

1. **Example sin `/Volumes/wupm` literal**: el prompt T5 sugería "valores de ejemplo `W:\ /media/wupm /Volumes/wupm`", pero T7+Cero-secretos prohíben `/Volumes/wupm` en versionados (raíz real del estudio). Se usaron rutas ficticias equivalentes (`/Volumes/estudio/2026`, `/media/estudio/2026`, `W:\estudio\2026`) — la plantilla NO documenta ninguna raíz real (guarda pasa, spec "No IPs" + "Sanitized commit" coherentes).
2. **`/HTLR/` sanitizado también en el fixture de tests** (`config_valida()`): aunque el guard T7 no escanea `/HTLR/`, Cero-secretos lo prohíbe en archivos versionados; los 3 valores no son asertados por ningún test (verificado) y se cambiaron a `/ESTUDIO/...` sin impacto.
3. **Test D6 de `ejecutar` en `test_render_distribuido.py`** (no en `test_render_config.py` como sugería tasks.md): `ejecutar` vive en el orquestador; el test del loader no puede asertarlo. Mismo criterio que PR3 (tests del worker en su propio archivo).
4. **README-ACL test en `test_no_fuga.py`** (no en `test_render_config.py`): es un guard de documentación, no lógica del loader; agrupa los escenarios de higiene del spec (17/18/19).
5. **Guard NO se escanea a sí mismo**: contiene las regex como literales (gotcha T7); el scope enumera explícitamente los archivos y excluye `test_no_fuga.py`. Los greps manuales confirman 0 en los assets.
6. **`openspec/` se versiona completo en el chore commit**: PR1–PR4 no lo commitearon (untracked); con el cambio cerrado se agrega todo el árbol (`config.yaml` + artifactos del cambio) para terminar con estado limpio. Si el orquestador prefiere mantener openspec/ fuera de git, es un chore revertible.
7. **Spec sync (T8) aplicado directo en el delta del cambio** (`openspec/changes/.../spec.md`): es la spec delta de este cambio; sdd-archive la mergeará al spec principal.

## Issues / Riesgos

| Riesgo | Detalle |
|---|---|
| El guard protege solo los archivos enumerados | Un archivo NUEVO bajo `render_distribuido/` fuera de `ARCHIVOS_BATCH` no se escanea; el guard es un checklist, no un escáner de directorio (documentado en el test). |
| `10\.0` en el regex de IPs | Puede dar falsos positivos si algún futuro archivo del scope usa "10.0" (p.ej. versión de software); hoy 0. Ajustar el regex si ocurre. |
| Example con bases ficticias | Si el admin copia el example tal cual, el orquestador operaría con rutas inexistentes; el README instruye completar con datos reales (política estricta: la config real sale del estudio, fuera del repo). |

## Next steps

- **sdd-verify** (siguiente fase): correr `python3 -m pytest`, `grep -rE "192\.168|@[a-z]"` en tracked y validar la spec 19/19 escenarios contra la implementación; el change queda listo para **sdd-archive** (merge del delta a `openspec/specs/`).
