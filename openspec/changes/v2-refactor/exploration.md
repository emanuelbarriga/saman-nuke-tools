# Exploration: V2 Refactor of saman-nuke-tools

> Change: `v2-refactor` · Phase: `sdd-explore` · Date: 2026-09-02
> Mode: read-only investigation. No source code was modified.
> Evidence: every claim below cites file:line against the current tree
> (`git HEAD` as of 2026-09-02; suite at 634 tests, all PASS).

## Executive Summary

The V2 tree as proposed loses or silently breaks four contracts that are not
represented in it: (1) the bootstrap update contract (exec of root `menu.py`,
checkout-completeness probe, auto-sync by hash, silence-without-checkout),
(2) the render anti-leak guard `tests/test_no_fuga.py` which hardcodes
`render_distribuido/*` paths, (3) the legacy `SamanTools.rutas` module that
saved comps import from their `knobChanged` expressions, and (4) the module
hub `registro.py` plus `proyecto.py`/`cambiar_colorspace.py`/`panel_rutas.py`/
`rutas_global.py`/`diagnostico_red.py`, none of which appear in the plan tree.
The UI/core policy is viable: 9 modules are already 100% pure (stdlib-only),
`panel_comentarios.py` hides ~60 pure module-level helpers behind one
`import nuke` (line 41), and a `test_no_fuga`-style guard can enforce the
boundary. Skills: NO new skills are needed — the 5 affected skills only need
path/contract updates (2 of them carry duplicated, already-diverged assets).
Phase order must change: the installer consolidation (Fase 2) depends on a
frozen layout and should move last; Fase 1 needs a pre-decision on the
compat shim and the `PYTHON_*` variable contract.

---

## A. What is lost if the plan is applied as-is

### A1. Update contract — `bootstrap/menu.py` (433 lines)

Current mechanism (all in `bootstrap/menu.py`, the file installed at
`~/.nuke/menu.py`):

| Concern | Function | Evidence |
|---|---|---|
| Checkout location | `TOOLS_DIR = ~/.nuke/SamanTools` — the git checkout IS the repo root | `bootstrap/menu.py:36` |
| Probe, no modify | `_estado_update()` → `'ok'\|'disponible'\|'error'\|'sin_checkout'\|'sin_git'` via `git fetch` + HEAD vs `origin/main` | `bootstrap/menu.py:76-95` |
| Version/commit shown | loads `SamanTools/__init__.py.__version__` from the checkout + short commit | `bootstrap/menu.py:98-120` |
| Consent-only apply | `_aplicar_update()` = `git pull --ff-only`; touches `LOCK_FILE` | `bootstrap/menu.py:123-143` |
| Manual button | no checkout → `nuke.ask` install → `_clonar_si_falta()`; else ask before pull | `bootstrap/menu.py:146-190` |
| Auto alert (6h) | `_alerta_automatica()` rate-limited by `LOCK_FILE`/`INTERVALO_SEG`; never applies alone | `bootstrap/menu.py:192-220`, `:38` |
| Uninstall | deletes checkout + `.desinstalado_*` + `~/.nuke/menu.py` only when it carries the marker "SamanTools" + "bootstrap de artista" | `bootstrap/menu.py:223-275` |
| No-checkout silence | `_agregar_boton_menu` only when checkout exists; boot never clones (error #8) | `bootstrap/menu.py:278-298`, `:423-430` |
| Clone tmp+rename | `_clonar_si_falta()` — never a partial checkout (error #4) | `bootstrap/menu.py:301-331` |
| Completeness probe | `_checkout_completo()` checks `TOOLS_DIR/SamanTools/registro.py` | `bootstrap/menu.py:334-343` |
| Repair | `_reparar_checkout()` = fetch + `reset --hard origin/main` | `bootstrap/menu.py:346-357` |
| Real loader | `_cargar_menu_real()` `exec`s `TOOLS_DIR/menu.py` (root loader) | `bootstrap/menu.py:360-391` |
| Bootstrap self-sync | `_auto_actualizar_bootstrap()` md5-compares `~/.nuke/menu.py` vs `bootstrap/menu.py`, `copy2` if different | `bootstrap/menu.py:394-420` |
| Entry | `instalar()` = auto-sync → exec → menu buttons → alert | `bootstrap/menu.py:423-430` |

The root loader that the bootstrap executes (`menu.py`, 46 lines) does:
`sys.path.append(REPO_DIR)` → `nuke.pluginAddPath(SamanTools/nodos)` →
`from SamanTools.registro import instalar; instalar()` (`menu.py:21-38`).

**What of the contract is NOT represented in the V2 tree:**

1. The **exec contract** between the bootstrap and the root loader. The plan
   moves `menu.py` into `nuke/` but nothing updates `_cargar_menu_real()`'s
   `repo_menu = os.path.join(TOOLS_DIR, "menu.py")` (`bootstrap/menu.py:372`).
   Silent break: the menu simply stops loading.
2. The **completeness probe** `_checkout_completo()` keys on
   `SamanTools/registro.py` (`bootstrap/menu.py:343`). The V2 tree has NO
   `registro.py` — after a partial clone/pull, the probe would misreport and
   `_reparar_checkout()` would run against a wrong marker.
3. The **silence-without-checkout** state depends on the two items above
   (`_tiene_checkout` checks `.git`; `_cargar_menu_real` returns `False`
   silently when `TOOLS_DIR` is absent). If the installer changes where the
   checkout lives, "sin_checkout" semantics change.
4. **Not in the tree at all**: `registro.py` (menu hub), `proyecto.py`,
   `cambiar_colorspace.py`, `panel_rutas.py`, `rutas_global.py`,
   `diagnostico_red.py` — the plan names `nuke/` root, `bootstrap/`,
   `SamanTools/{core,ui,vfxflow,nodos}/` and `render/`, and nothing else.

**Can an `installer.py` inside the checkout replace `instalar_script_editor.py`
(autocontained today)?** Partially. The four real install flows:

| Flow | Entry | Needs | Decision it requires |
|---|---|---|---|
| F1 — Script Editor (inside Nuke) | `instalar_script_editor.py` (92 lines, paste-able, 3 states: git→pull / copy-old→backup+clone / none→clone; copies bootstrap) | `nuke` + git | consent via `nuke.message`; keep paste-able idempotency |
| F2 — Terminal `curl \| bash` (no repo) | `setup_artista.sh:9,40-46` downloads `bootstrap/menu.py` from the raw URL itself, then clone or `reset --hard` | bash + git, NO python, NO nuke | hardcoded `REPO_URL=emanuelbarriga/...` (`setup_artista.sh:22-25`) |
| F3 — Terminal / Windows from checkout | `setup_artista.sh:37-39` local `BOOTSTRAP_SRC`; `setup_artista.bat:13` takes `REPO_URL` as ARG and injects it into `menu.py` via PowerShell replace of `TU_ORG` (`setup_artista.bat:44`) | bash/bat + git | **fork-ability**: `.bat` supports a fork URL, `.sh`/`instalar_script_editor.py`/`bootstrap/menu.py:32` hardcode it |
| F4 — In-Nuke repair/reinstall button | `bootstrap/menu.py:146-190, 301-331` (`_actualizar_ahora` → `_clonar_si_falta`) | nuke + git | consent; never runs at boot (error #8) |

Legacy `install.sh`/`install.bat` (copy, no git) are off-limits by rule
(`docs/ARQUITECTURA.md:142`; `openspec/config.yaml` rules.proposal).

A repo-internal `installer.py` can unify F1 (same code pasted/exec), F3/F4
(repo-relative run) — but F2 needs a **zero-dependency entry** (bash that
fetches the installer over raw URL and can still install without python3 on
PATH). An `installer.py` alone does not replace F2 unless the project accepts
"python3 required on artist terminals" (not guaranteed; Nuke's embedded Python
is not on PATH). Concrete decision needed: single repo-URL policy (drop
fork-ability) vs keep per-flow URL override.

### A2. render_distribuido — what protects it today and what breaking moves

- **Specs** (source of truth): `openspec/specs/{render-config-central, render-multinodo, render-qc-plate, render-shot-selection}/spec.md`; archived copies at `openspec/changes/archive/2026-09-02-render-*/`.
- **Tests**: `test_render_config` (50), `test_multinodo` (34), `test_render_distribuido` (32), `test_qc_plate` (32), `test_seleccion` (23), `test_layouts` (12), `test_render_worker` (7), `test_no_fuga` (6).
- **Guard `tests/test_no_fuga.py`** hardcodes the batch scope: `ARCHIVOS_BATCH` lists `render_distribuido/<file>` paths and `tests/test_<batch>.py` (`test_no_fuga.py:31-47`), `ARCHIVOS_PRODUCCION` filter uses `p.startswith("render_distribuido/")` (`:51`), `_archivo()` asserts each file exists (`:58-61`), and two tests read `render_distribuido/studio_config.example.json` + `render_distribuido/README.md` directly (`:109-111, 124`). Moving to `render/` breaks **all of these at once**. It is not an automatic loss — it is a coupled edit that MUST land in the same commit as the move, or the suite turns red at that commit.
- **Coupling to SamanTools (entorno.py)**: exactly one lazy coupling point —
  `render_config.py:_cargar_entorno()` imports `SamanTools.entorno` with a
  sys.path shim `_agregar_raiz_repo_a_syspath()` whose root computation is
  `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
  (`render_config.py:71-97`) — valid only while the file sits exactly one
  level under the repo root. It calls `mod.primera_ruta_disponible(mod.detectar_so())` (`render_config.py:113`) and `estado_unidad` (`:129`). If `entorno.py` moves to `SamanTools/core/entorno.py` the import becomes `SamanTools.core.entorno` — the shim must be updated; if `render/` is at root the double-dirname still works, but if it nests deeper it breaks.
- Also relevant: `render_worker.py:15-16` does `import nuke` + `import __main__` — it is NOT nuke-free (it must run inside headless Nuke to render). "render_* (todo headless)" is only true for `layouts.py`, `plate_qc.py`, `render_config.py` and the orchestrator `render_distribuido.py` (all stdlib-only, verified).

### A3. `proyecto.py` and `cambiar_colorspace.py` — confirmed, and tree gaps

Both exist and both are **absent from the V2 tree**:

- `SamanTools/proyecto.py` (140 lines) — dynamic per-project tool loading from `{PYTHON_COMP}/Scripts`: `SUBMENU = "HTLR · Saman · Samán · Galerías"` (`:15`), `cargar_scripts_proyecto()` (`:90`) walks `.gizmo/.nk`, classifies `Galerías`/`Herramientas` (`PALABRAS_GALERIA :75-78`, `_clasificar :81`), registers under `nuke.menu("Nodes")`, and **always removes the previous submenu first** (`:104-106`). Called by `registro.instalar()` (`registro.py:345`) and by `rutas._aplicar_config()` (`rutas.py:240`). Its pure parts (`_escanear :57-70`, `_clasificar :81-86`) are testable; the menu logic is UI.
- `SamanTools/cambiar_colorspace.py` (117 lines) — PySide `QDialog` (`VentanaCambioColorSpace :9`) + `ejecutar_cambio_colorespace_reads()` (`:79`) that detects OCIO backend (`nuke.usingOcio()`/`nuke.getOcioColorSpaces()`), applies `fromScript` + `reload` on selected Reads. Registered with icon `ChangeColorSpace.svg` (`registro.py:286-290`).
- Other gaps in the plan tree: `registro.py` (menu hub), `panel_rutas.py` (docked global panel), `rutas_global.py` (JSON persistence + `aplicar_global`), `diagnostico_red.py`, and the legacy `rutas.py` itself.
- Shortcut surface: today `Ctrl+Alt+C` = Panel de Comentarios (`registro.py:298-302`). The plan proposes `Ctrl+Alt+R/E/V` for the new panels — no collision today, but the plan must define the full shortcut map once (including what happens to `Ctrl+Alt+C` and the "Panel de Rutas" command, `registro.py:311-314`).

### A4. Fragile invariants to preserve (named)

1. **`es_nodo_rutas()` detector** — `rutas.py:560-583`: knob `UsuarioActivo` + any of `TO_VFX_SERVER_MAC/WINDOWS/ARTIST`; deliberately NOT `RutaActual` (removed in v1.1.2). Node "version" = `KNOBS_VERSION_ACTUAL` (`rutas.py:524-534`); 9 base knobs = `KNOBS_RUTAS_BASE` (`:385-389`).
2. **`Rutas.gizmo` = exact mirror of the `NoOp` block of `Rutas.nk`** — verified byte-identical today (`Rutas.nk` = 9 header comment lines + the 65-line `NoOp` block; `Rutas.gizmo` = that block). Regeneration: `sed -n '/^NoOp {/,$p' SamanTools/nodos/Rutas.nk > SamanTools/nodos/Rutas.gizmo` (rule in `docs/ARQUITECTURA.md:115-116`, maintenance skill).
   - **Hazard the plan does not address**: the node's `knobChanged` expression does `from SamanTools import rutas` (`Rutas.nk:12`). Every comp saved with a Rutas node imports `SamanTools.rutas` at load time. If `rutas.py` moves/renames to `core/rutas_engine.py`, **saved comps break** unless a re-export shim (`SamanTools/rutas.py`) survives — the knobs migration mechanism is `_KNOBS_A_MIGRAR`-driven (`rutas.py:536-548`), and `crear_o_reutilizar()` (`:734`) pastes the `.nk` for new nodes; old ones stay.
3. **`registro.py`** — TAB search submenu `"HTLR · Saman · Samán"` for FIXED tools (`registro.py:368`) vs `proyecto.py` `"HTLR · Saman · Samán · Galerías"` for DYNAMIC tools (`proyecto.py:15`) — two different submenus that must not merge; `_inyectar_frame_manager()` (`registro.py:257-273`) adds the SamanTools package dir to `sys.path` + imports `frame_manager` so the Breakdown gizmo's PyCustom knob `__import__('frame_manager').FrameManagerKnob()` resolves globally; "Insertar Nodo" commands Rutas/Review/Breakdown (`registro.py:371-383`).
4. **`tests/conftest.py` stub** — injects a fake `__main__` with `PYTHON_TO_VFX/COMP/FROM_VFX` (`conftest.py:18-36`), a fake `nuke` module (`:39-218`), `NodoFake.__getitem__` returning a default `KnobFake()` for missing knobs (`:88-89` — deliberately does NOT catch missing-knob bugs; real Nuke raises `ValueError`, the `RutaActual` v1.1.2 lesson, `docs/ARQUITECTURA.md:117-120`), `MenuFake` with `_items` vs method `items()` (`:149-161`). Every module move forces its test-import update in the same commit (verified map): `test_entorno`, `test_rutas`, `test_gestion_rutas`, `test_rutas_global`, `test_proyecto`, `test_registro`, `test_menu`, `test_limpiar`, `test_nombres`, `test_cambiar_colorspace`, `test_diagnostico_red`, `test_vfxflow_*`.

---

## B. UI/core separation policy

### B5. Inventory: pure vs UI (verified by imports)

**Pure today (stdlib-only, no `import nuke`/PySide at module top):**
`entorno.py` (os/platform/string/subprocess/time) · `nombres.py` (os/re + entorno) · `limpiar.py` (os/re) · `vfxflow_config.py` (json/os) · `sesion_vfxflow.py` (json/os) · `vfxflow_auth.py` (stdlib only + `from . import vfxflow_config`; 0 `nuke.` uses) · `vfxflow_datos.py` (imports the two above; 0 `nuke.`) · `layouts.py` · `plate_qc.py` · `render_config.py` (stdlib + **lazy** `SamanTools.entorno` via shim) · orchestrator `render_distribuido.py`.

**Partial in `rutas.py`:** `_reescribir_proyecto_en_rutas()` pure (`rutas.py:245-267`, re+dict) · `_aplicar_config()` config-driven but writes `__main__` AND calls `proyecto.cargar_scripts_proyecto()` (nuke menu) (`:208-242`) · **`_capturar_reads_dinamicos()` is NOT pure** — it uses `nuke.allNodes("Read")` (`:181-190`) — and `_re_evaluar_y_recargar`/`actualizar`/node knobs are nuke-bound. `rutas_global.py` persists pure (config_vacia/cargar/guardar/cambiar_proyecto_global/importar_desde_nodo) but `aplicar_global` touches nuke reads.

**Boundary line:** the frontier is exactly "modules that `import nuke` or PySide at top" vs not. Current UI layer: `registro.py`, `proyecto.py`, `panel_rutas.py`, `panel_comentarios.py`, `frame_manager.py`, `cambiar_colorspace.py`, plus `render_worker.py` (nuke-bound by design) and both `menu.py` files.

**Pure logic hidden inside UI modules:**
- `panel_comentarios.py` (4267 lines, `import nuke` at `:41`) hides ~60 module-level helpers behind that one import: formatting/parsing (`_markdown_bold`, `_escapar_y_linkificar`, `_tiempo_relativo(+largo)`, `_inicial_avatar`, `_abreviar_nombre`, `_resumen_asignados`, `_glifo_tipo`, `_verbo_tipo`, `_formatear_version`, `_versiones_diferentes`, `_texto_tarea`, `_texto_asignacion`, `_formatear_tamano_bytes` `:368-691`), context (`_ep_desde_ruta`, `_ruta_read_ref`, `_ruta_jpg_temporal`, `_ruta_destino_refs`, `_filename_desde_url_ref`, `_timestamp_export`, `_nombre_export_jpg`, `_convertir_jpg_1280x720`, `_rect_crop_central` `:652-1156`), firestore payloads (`_iso_ahora`, `_encode_valor_firestore`, `_payload_actividad`, `_base_campos_actividad`, `_campos_status_change`, `_nombre_usuario_sesion`, `_rol_sesion` `:908-1027`), state helpers (`_ids_estados`, `_color_estado_chip`, `_indices_estado_anterior_siguiente`, `_acciones_estado` `:843-1084`), and the module-level uploader `_subir_imagen_storage` (`:4174`). ~157 tests (`test_panel_comentarios.py`) already exercise them through the conftest stub.
- `frame_manager.py` (328 lines): model = the `frame_data` JSON contract `[{frame,brillo,muzzle,humo,impacto,sangre}]` + `cargar_datos()`/`guardar_datos()` (`:231-278`) and `_swap_rows` (`:193`) — pure; view = `FrameManagerTable(QTableWidget)` (`:36`) with cell writers `_celda_check`, `on_cell_changed`, `actualizar_frames_en_vivo`; controller = `generar()` (`:110`) which rebuilds the FrameHold/Text2/ContactSheet graph via nuke.

### B6. Proposed architecture rule (sketch, not final design)

- **Rule**: modules under `core/` and the pure render layer MUST NOT import `nuke`, `nukescripts`, `PySide2`, or `PySide6`; UI modules live under `ui/` and are the only ones that may. UI modules must not hold business logic beyond widget plumbing (they delegate to `core/`).
- **Enforcement**: a `test_no_fuga`-style guard, e.g. `tests/test_no_import_nuke_en_core.py`, that scans the layer's `.py` files with a line-anchored regex `^(import nuke|from nuke|import nukescripts|from nukescripts|import PySide2|from PySide2|import PySide6|from PySide6)` and fails the suite if found — exactly the pattern `test_no_fuga.py` uses (path list + parametrized `_hallazgos`), so it only matches import statements, never comments/docstrings (two legit comment mentions exist today: `vfxflow_auth.py:6` "sin `import nuke`" and `render_distribuido.py:293` "nuke.execute").
- **Caveats**: (1) a positive twin guard can assert every `ui/` module still imports cleanly under the conftest stub; (2) the rule needs an explicit exemption list for `render_worker.py` (nuke-bound by design) and both `menu.py`s; (3) the strict-stub gap (`NodoFake.__getitem__`) should be revisited: consider a strict mode raising on missing knobs so restructures of the Rutas node are caught by tests (ARQUITECTURA lesson).

---

## C. Skills

### C7. Inventory of the 7 skills — duplication, machine paths, refactor impact

| Skill | Duplicated assets | Machine/HTLR paths | Depends on V2 refactor? |
|---|---|---|---|
| `davinci-timeline-comments` | none | Resolve app paths | **No** — standalone Resolve skill, zero SamanTools coupling |
| `nuke-breakdown-gizmo` | **YES**: `assets/frame_manager.py` (319 lines) vs `SamanTools/frame_manager.py` (328 lines) — **DIVERGED** (skill copy lacks the `pparent` scoping bugfix, `SamanTools/frame_manager.py:124-133`); `assets/Breakdown.gizmo` == `SamanTools/nodos/Breakdown.gizmo` (byte-identical) | `~/.nuke/SamanTools/...` deployed paths (`SKILL.md:18,62-65,71,81`) | **Yes** — references `SamanTools/registro.py._inyectar_frame_manager()`, `nodos/Breakdown.gizmo`, TAB submenu; needs update when `frame_manager.py` → `ui/` and if the injected `sys.path` mechanism changes |
| `nuke-gallery-gizmo` | none (generator `assets/build_gallery_gizmo.py` is its own asset) | `HTLR/COMP/Scripts/MuzzleHTLR.gizmo`, `HTLR/COMP/GLOBAL_ASSETS/` (`SKILL.md:73-74`) | Partial — uses `from SamanTools.limpiar import sanitizar_archivo` (`SKILL.md:59`); breaks only if `limpiar` import path changes to `SamanTools.core.limpiar` |
| `nuke-project-clone` | none | `HTLR/COMP/EP_100/...` template (`SKILL.md:61-62`) | **Yes** — depends on the `PYTHON_TO_VFX/COMP/FROM_VFX` variable contract ("Variables come from the RUTAS2 node", `SKILL.md:20`) and on `parsear_plato` naming conventions; also calls the sanitizer via repo path |
| `render-red` | none | HTLR/IPYD/PCF layout names as data (by design) | **Yes** — references `render_distribuido/*` paths and the exact command `python3 render_distribuido/render_distribuido.py` (`SKILL.md:62,84-89`) |
| `saman-nuke-tools-maintenance` | `assets/verificar_salud.py` (health index, own asset) | repo paths | **Yes** — names `instalar_script_editor.py` (`SKILL.md:65`), `setup_artista.*` (`:18`), `SamanTools/rutas.py`/`entorno.py` (`:66`) as the official flow; installer consolidation + core/ move invalidate it |
| `vfxflow-panel-comentarios` | none | Firebase endpoint data only | **Yes** — references `SamanTools/panel_comentarios.py` and `SamanTools/nombres.py.parsear_plato` (`SKILL.md:109-110`); the split `vfxflow/core + ui` changes both references |

Also relevant: `docs/ARQUITECTURA.md:143-144` requires skills to live versioned in `skills/` and be symlinked by the HTLR project into `.opencode/skills` — edits always happen in the repo. The fix for the diverged `frame_manager.py` copy is to make the skill reference the canonical file (or re-sync), NOT to keep two sources.

**Verdict — new skills vs updates:** NO new skills are required for V2. Every affected skill is an existing one needing only path/contract updates (5 of 7; `davinci-timeline-comments` untouched). The one genuinely new decision — the UI/core layer policy — belongs in `saman-nuke-tools-maintenance` (or `docs/ARQUITECTURA.md`) plus the new guard test, not in a new skill.

---

## D. Phase-order risks

Plan order: (1) motor+constantes `rutas_engine` → (2) installer único → (3) monolith decoupling + skill dedupe → (4) PySide panels.

- **Fase 1 cannot start blind**: `rutas_engine.py` presupposes the destination of `rutas.py`, `Rutas.nk/.gizmo` and the compat question. Saved comps call `from SamanTools import rutas` via the node's `knobChanged` (`Rutas.nk:12`). Without a pre-decision (re-export shim vs forced node migration), Fase 1 is unimplementable — the "motor central" would fork the truth while old comps keep using the adapter.
- **Fase 2 (installer) is premature at position 2**: the installer must install the FINAL tree, and the bootstrap probes (`_checkout_completo` → `SamanTools/registro.py`, `_cargar_menu_real` → `TOOLS_DIR/menu.py`, `_auto_actualizar_bootstrap` → `bootstrap/menu.py`) only make sense once the layout is frozen. Recommend moving the installer consolidation to the END (after layout + moves), or at least gating it behind the layout freeze.
- **Fase 3 (decouple + dedupe) depends on Fase 1's paths** (skills reference `rutas.py`/`entorno.py`/`panel_comentarios.py`) — 3 must follow 1.
- **Fase 4 (panels) depends on the UI/core rule established in 3** — 4 follows 3; panels must be born compliant with the guard.
- **Coupled constraint**: the `render/` move forces a simultaneous edit of `test_no_fuga.py` (hardcoded scope), the `render_config` sys.path shim, and `render-red` SKILL.md. Whichever fase touches `render/` must carry those three in the same commit.
- **Test-import map**: any move of `entorno/rutas/rutas_global/proyecto/registro/limpiar/nombres/cambiar_colorspace/diagnostico_red/vfxflow_*` breaks its test imports (verified list in A4) — mechanical but must be atomic per commit.

**Recommended order**: pre-decision (compat shim + `PYTHON_*` contract + layer rule) → Fase 1 (motor) → Fase 3 (decouple + skills + guard, incl. render/ move with `test_no_fuga` update) → Fase 4 (panels) → Fase 2 (installer) LAST.

---

## Risks

- **CRITICAL — `nuke/` top folder shadows the `nuke` module**: with the repo root in `sys.path` (root loader does `sys.path.append(REPO_DIR)`, `menu.py:25`), a namespace package named `nuke/` at the root risks shadowing the real `nuke` module for imports resolved after the path append; also under pytest. Needs a different top-level name (e.g. `saman/`) or strict sys.path hygiene.
- **CRITICAL — saved comps break on `rutas.py` removal**: `knobChanged` does `from SamanTools import rutas` (`Rutas.nk:12`); requires a re-export shim or a node-migration plan; `Rutas.gizmo` mirror must be regenerated in the same commit.
- **CRITICAL — bootstrap contract paths break silently**: `_checkout_completo` probe (`bootstrap/menu.py:343`), exec target (`:372`) and auto-sync source (`:403`) reference pre-V2 paths; a broken probe silently degrades the "no-checkout = silence" state.
- **CRITICAL — `test_no_fuga.py` hardcodes `render_distribuido/*`** (`test_no_fuga.py:31-51, 109-126`); the `render/` move must update it atomically or the suite fails at that commit.
- **WARNING — `registro.py` absent from the plan tree**: menu hub, TAB submenus, `_inyectar_frame_manager` and all "Insertar Nodo" commands have no destination; the plan must name their home.
- **WARNING — `proyecto.py`/`cambiar_colorspace.py`/`panel_rutas.py`/`rutas_global.py`/`diagnostico_red.py` absent**: per-project TAB loading ("· Galerías"), the OCIO dialog (+ icon), the docked global panel and its JSON store would disappear; shortcut map (existing `Ctrl+Alt+C`) vs new `Ctrl+Alt+R/E/V` must be defined together.
- **WARNING — `PYTHON_TO_VFX/COMP/FROM_VFX` is a public contract** written to `__main__` (`rutas.py:234-236`) and consumed by saved comps, `nuke-project-clone`, gallery gizmos, `panel_rutas` and `rutas_global`; `rutas_engine` must keep the names or everything downstream breaks.
- **WARNING — skill deployed-path references change with depth**: `~/.nuke/SamanTools/nodos/...` becomes `~/.nuke/SamanTools/nuke/SamanTools/nodos/...` in V2 (checkout location unchanged); all 5 affected skills need co-updates, plus the diverged `frame_manager.py` asset (dedupe decision).
- **SUGGESTION — UI/core guard must match only import statements**, not comments/docstrings (`vfxflow_auth.py:6`, `render_distribuido.py:293` legitimately mention `nuke`).
- **SUGGESTION — stub strict mode**: `NodoFake.__getitem__` returning `KnobFake()` hides missing-knob bugs during restructures (ARQUITECTURA l.117-120); consider a strict option.

## Ready for Proposal

**Yes**, conditioned on: (1) resolving the `nuke/` shadowing (rename top folder), (2) committing to the `SamanTools.rutas` compat shim (or explicit node-migration), (3) naming the home of `registro.py`+gaps, and (4) accepting the recommended phase order (installer last). The proposal should also carry the UI/core rule + guard test as a first-class requirement.