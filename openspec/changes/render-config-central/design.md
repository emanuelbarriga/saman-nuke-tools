# Design: Config central de infraestructura del orquestador de render

## Technical Approach

Capa estricta `render_config.py` (puro, testeable sin Nuke) que replica el patrón vfxflow — base `entorno.primera_ruta_disponible()` → `{base}/.saman/studio_config.json` → `config_local.py` (`RENDER_LOCAL_CONFIG`, gitignored) — con política ESTRICTA: sin fuente esquema-completa ⇒ `SystemExit` diferenciado (FileNotFoundError → "copiar example"; OSError/TimeoutError → "mount/red"). Un validador único acumula TODAS las faltantes/tipos (spec: Schema integrity) y re-verifica la completitud del local (spec: Local complete, no disk). `traducir_ruta()` generaliza `template_local()` sobre `bases_por_so` con normalización de separadores vía `PurePosixPath`/`PureWindowsPath` (spec: Multi-OS path translation). Refactor de orquestador y worker para leer workers/sufijos/bases de config; primer commit sanitizado de `render_distribuido/`.

## Architecture Decisions

| Decisión | Elección | Rationale |
|---|---|---|
| **D1 firma `traducir_ruta`** | `traducir_ruta(ruta, desde_so, hacia_so, config) -> str` + `detectar_so_de_ruta(ruta, config)` + `_canon()` (PurePosixPath) + `normalizar_separadores(ruta, so)` (Windows ⇒ `str(PureWindowsPath)`) | desde/hacia explícitos ⇒ tests deterministas; Pure*Path normaliza separadores al SO destino (spec esc. 4-5). Alternativas rechazadas: regex `/mnt`↔`/Volumes` (par hardcodeado), `os.path.normpath` (sin control cross-OS), estado global (impuro). Ruta fuera de prefijos ⇒ intacta (spec: Unknown prefix) |
| **D2 distribución de bases** | `bases_por_so`: dict OS→ruta única. `worker.base` OBLIGATORIA y debe caer bajo una base declarada (integridad: `canon.startswith(base_os + "/")`) | Sin SO en el esquema del worker ⇒ herencia ambigua; unión sin OS ⇒ no decide separadores destino. Una ruta canónica por SO + regla de prefijo ⇒ todo template reportado es traducible (evita falso 0). Alternativas rechazadas: herencia, mapa-unión |
| **D3 forma de `RENDER_LOCAL_CONFIG`** | Dict top-level con las MISMAS llaves del esquema, merge por llave sobre el JSON; validador único sobre el resultado | Merge per-key sobre dicts del mismo esquema; un validador = una verdad de forma. Rechazadas: scalares planos, defaults versionados (violan política estricta) |
| **D4 gate de mount** | Gate de mount ANTES de open solo si la base viene de `entorno`; timeout con margen WAN: ver D7 (supersede el 3s de esta fila); catch directo OSError/FileNotFoundError como red; base por env (`RENDER_CONFIG_BASE`) salta el gate | Carga 1 vez por corrida ⇒ costo despreciable vs. open() colgado en mount SMB. Rechazada: open() directo solo (hang no acotado). FileNotFoundError con unidad conectada sigue sugiriendo example |
| **D5 entorno lazy** | `from SamanTools import entorno` lazy; en ImportError (script run) insertar repo-root en sys.path y reintentar | `python3 render_distribuido.py` ⇒ sys.path[0] = su dir; SamanTools no importable sin el shim. Patrón lazy de vfxflow adaptado a repo-relative |
| **D6 explicit env in SSH** | `ejecutar()` composes the remote command with EXPLICIT inline env: `env KEY='val' ... <cmd>` (plus `LC_ALL=C` prefix for Linux workers) — NEVER relying on sshd AcceptEnv/env inheritance. Worker consumes ONLY `os.environ` (no hardcoded defaults) | Verified in code: `render_distribuido.py::ejecutar` already builds `"env %s%s %s"` from the env dict (line 73); explicit env works regardless of remote sshd config and is already implemented/proven. Rejected: `SendEnv`/`AcceptEnv` (sshd-dependent, silent failure); stdin/argv CLI delivery (possible reinforcement only — design chooses explicit env) |
| **D7 WAN mount-gate margin** | Mount gate runs up to 2 attempts × 3s (6s budget) via orchestrator-local helper `_gate_mount(base, timeout=3, intentos=2)`; mount declared down ONLY after both attempts fail; global `TIMEOUT_SEGUNDOS` in `entorno.py` untouched (timeout parametrized locally in `render_config.py`) | `estado_unidad`'s single 3s check can false-negative on cold WAN (remote LucidLink). 2×3s costs ≤6s once per run (negligible). GOTCHA verified in code: `estado_unidad` caches 10s INCLUDING timeout results (`_cache[ruta] = (ahora, res)`) — a retry through it would be a no-op, so the gate re-runs its own `ls -d` subprocess check with local timeout, cache-free. Rejected: raising global `TIMEOUT_SEGUNDOS` (changes app-wide UI behavior), single 3s check (WAN flaky) |
| **D8 `.saman` ACL vs worker reads** | LucidLink ACL on `{base}/.saman/studio_config.json`: admin = WRITE; READ granted to workers' `ssh_user` (minimum: render group/machines). Operational fallback: a node that cannot read the JSON gets the complete config in `config_local.py` (`RENDER_LOCAL_CONFIG`, local-complete-no-disk autonomy already supported). Verification criterion: worker users can `cat {base}/.saman/studio_config.json` OR hold a full `RENDER_LOCAL_CONFIG`. Risk: verify ACL in LucidLink panel BEFORE rollout | Admin-only config breaks workers running as artist accounts (e.g. `ART_PACIFICO`) — config is infrastructure, not secret, so read must reach render nodes. Rejected: admin-only read/write (spec v1 wording; breaks workers), world-readable (uncontrolled). NOTE: spec line "admin-ONLY read/write" + scenario "ACL documented" need a MODIFIED delta (see Open Questions) |

## Data Flow

```
RENDER_CONFIG_BASE (env) ─┐
entorno.primera_ruta_disponible ─┴→ base → {base}/.saman/studio_config.json ─┐
config_local.py (RENDER_LOCAL_CONFIG) ──────────────────────────────────────┴→ merge per key
        ▼
validar_esquema() → errores acumulados ──→ SystemExit (TODAS + arreglo)
        │ (válido)
        ▼
render_distribuido.py ── workers/sufijos → argparse defaults, template_local()
        │                                        │
        ▼ env BASE/TO_SUF/COMP_SUF/FROM_SUF       ▼ traducir_ruta(desde=detectar_so_de_ruta,
        (explicit `env KEY='val' ...` on              hacia=SO local)
        the remote command line — D6)
render_worker.py (sufijos SOLO desde env)
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `render_distribuido/render_config.py` | Create | Cadena estricta, `validar_esquema()`, merge, `traducir_ruta()`, `detectar_so_de_ruta()`, `_canon()`, `normalizar_separadores()`, lazy entorno con shim |
| `render_distribuido/render_distribuido.py` | Modify | Quitar `WORKERS`/`BASE_MAC`/`BASE_LINUX`/sufijos-defaults (default `None`, resueltos desde config tras parse); `ssh` = `f"{ssh_user}@{ssh}"`; `bin`→`nuke_exec`; `template_local(template, config)` vía traducción |
| `render_distribuido/render_worker.py` | Modify | `setear_variables`: `os.environ.get("TO_SUF", "")` etc. — sin fallbacks `/HTLR/...`; worker consumes env ONLY via `os.environ` (no hardcoded defaults) — D6 |
| `render_distribuido/studio_config.example.json` | Create | Conforme al esquema, hostnames/DNS, sin IPs |
| `render_distribuido/README.md` | Create | Patrón, ubicación real, pasos de creación, ACL (admin WRITE, workers-render READ — D8), fallback `RENDER_LOCAL_CONFIG`, criterio de verificación, overrides, traducción multi-SO |
| `docs/ARQUITECTURA.md` | Modify | Nota ACL corregida (D8): LucidLink ACL = admin WRITE + READ para `ssh_user` de workers (grupo/máquinas render) sobre `{base}/.saman/studio_config.json`; fallback nodo = `RENDER_LOCAL_CONFIG` completo; verificación: `cat {base}/.saman/studio_config.json` con cuenta worker o local completo |
| `tests/test_render_config.py` | Create | pytest puro: merge, env override, abort estricto, faltantes, tipos, traducción, example válido, env explícito en `ejecutar()`, gate 2×3s |

## Interfaces / Contracts

```python
ARCHIVO_DISCO = ".saman/studio_config.json"
ENV_BASE = "RENDER_CONFIG_BASE"               # override de base por env
def obtener_config_efectiva() -> dict: ...    # ESTRICTA: SystemExit con diagnóstico
def validar_esquema(config) -> list[str]: ... # puro; [] = ok; errores con key path + arreglo
def traducir_ruta(ruta, desde_so, hacia_so, config) -> str: ...
def detectar_so_de_ruta(ruta, config) -> str | None: ...  # longest-prefix
def mapa_bases(config) -> dict[str, str]: ...  # {so: base_canon}

# Esquema: {"bases_por_so": {os: str}, "workers": [{nombre: str, ssh: str|None,
#   ssh_user: str, nuke_exec: str, base: str, lc_all: bool}],
#   "sufijos": {TO_VFX: str, COMP: str, FROM_VFX: str}}  (example = plantilla válida)

# Remote command contract (D6): orchestrator composes the remote argv with
# EXPLICIT inline env — never sshd AcceptEnv/inheritance:
#   ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", worker.ssh,
#    "env", "LC_ALL=C", "BASE='...'", "TO_SUF='...'", "<nuke cmd>"]   # linux
def _gate_mount(base, timeout=3, intentos=2) -> bool: ...  # mount gate (D7), local timeout
```

Normalización: `_canon(ruta)` ⇒ `PurePosixPath(ruta.replace("\\","/")).as_posix()` sin trailing `/`; render Windows ⇒ `str(PureWindowsPath(canon))` (`W:\wupm\2026\PCF\TO_VFX\x.nk`); POSIX ⇒ canon. Traducción: si `canon` no cae bajo base de `desde_so` (o par no declarado) ⇒ intacta; si no, `base_hacia + resto` render al SO destino.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit (loader) | merge per-key; env override; local completo sin disco; local incompleto aborta; FileNotFound→"copiar example"; OSError→"mount" sin template | pytest, base env a tmp_path + monkeypatch open/entorno |
| Unit (validador) | múltiples faltantes en UN SystemExit (key paths), tipo incorrecto, worker.base fuera de prefijos, example válido | `validar_esquema()` + `obtener_config_efectiva()` |
| Unit (traducción) | pares macOS/Windows/Linux × ambos sentidos, separadores, prefijo desconocido intacto | `traducir_ruta` con config en memoria |
| Unit (env explícito) | `ejecutar()` composes `env KEY='val' ...` on the remote argv (no AcceptEnv dependency); worker parses sufs only from `os.environ` | monkeypatch `subprocess.run`, assert argv; RED test per threat row |
| Unit (gate WAN) | `_gate_mount` retries 2×3s before declaring mount down; first timeout → retry → ok; both fail → down; uses local timeout, cache-free | monkeypatch `subprocess.run` (sleep/timeout), base a tmp_path |
| E2E | — | N/A (stub nuke existente) |

## Threat Matrix

| Boundary | Applicability |
|---|---|
| Documentation-like paths | N/A — example JSON/README no ejecutables |
| Git repository selection | N/A — sin lógica git nueva (commit sanitizado es humano) |
| Commit state | N/A — sin index/worktree automation |
| Push state | N/A — sin refspec/push automation |
| PR commands | N/A — sin composición de comandos PR |
| Remote command/env composition (`ejecutar`) | **Applicable** — orchestrator builds the remote argv with explicit inline env |

**Remote command/env composition (Applicable)**: safe behavior = `env KEY='val' ... <cmd>` composed from the config env dict with `%s='%s'` quoting, argv passed as a list (no local shell, no interpolation of worker/`--workers` names into shell); failure behavior = ssh non-zero returncode + stderr propagated to the user, never faked success; test boundary = RED test asserts `subprocess.run` receives an argv whose first remote token is `env` followed by `KEY='val'` pairs, and that a worker name with shell metacharacters stays inert (filtered before the argv). Nota: `ejecutar()` composes ssh/env like today (separate argv, no local shell); only the data provenance changes (code → config admin). `--workers` filters by name and never reaches the shell.

## Migration / Rollout

No migration. Admin crea `{base}/.saman/studio_config.json` (LucidLink) desde el example. Con política estricta el orquestador queda inoperante hasta tener config (por diseño, mensaje-guía). Rollback: `git revert` del commit sanitizado; config real fuera de repo.

ACL rollout (D8): ANTES del rollout, verificar en el panel de LucidLink que los `ssh_user` de los workers (mínimo grupo/máquinas render) tienen READ de `{base}/.saman/studio_config.json` y admin WRITE. Fallback operativo: si un worker no puede leer el JSON, distribuir la config completa en `config_local.py` (`RENDER_LOCAL_CONFIG`) en ese nodo (autonomía local-completa ya soportada). Criterio de verificación operativa: los usuarios workers pueden `cat {base}/.saman/studio_config.json`, o el nodo tiene `RENDER_LOCAL_CONFIG` completo.

## Open Questions

- [ ] Spec sync (D8): requirement "Public template, docs, tests, sanitized commit" ("admin-ONLY read/write" wording) + scenario "ACL documented" MUST be updated via a MODIFIED delta to admin-WRITE/workers-READ — decide in sdd-tasks or a follow-up spec delta; the design already carries the corrected behavior, but spec and design must not diverge at verify time.