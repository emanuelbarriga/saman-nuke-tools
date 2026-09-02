# Tasks: render-config-central — Central infra config (strict loader, multi-OS translation, sanitized first tracking)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1,250–1,450 (incl. ~650L one-time tracking of untracked `render_distribuido/`) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 → PR 2 → PR 3 → PR 4 → PR 5 |
| Delivery strategy | auto-chain |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | T1 chain+validator+merge+strict policy (+tests) | PR 1 (~290) | `pytest tests/test_render_config.py -k "carga or esquema or estricto"` | N/A — stdlib unit via nuke stub; bases mocked (tmp_path) | revert render_config.py + tests |
| 2 | T2 traducir_ruta/_canon/separadores + _gate_mount (+tests) | PR 2 (~180) | `pytest tests/test_render_config.py -k "traducir or gate"` | N/A — in-memory config, no mount | revert translation fns + tests |
| 3 | T4 render_worker env-only D6 (+tests) | PR 3 (~240) | `pytest tests/test_render_config.py -k "env"` | N/A — remote nuke unreachable from dev; parsing unit-tested | revert render_worker.py |
| 4 | T3 render_distribuido.py config-driven + env argv D6 | PR 4 (~480, full-file first tracking) | `python3 -m pytest` | N/A — smoke needs real studio; slice >400 ⇒ size:exception candidate | revert render_distribuido.py |
| 5 | T5 example/README/ACL + T6 example test + T7 anti-leak + T8 spec sync | PR 5 (~190) | `pytest tests/test_render_config.py -k example && git grep -E "192\.168|@"` | grep scan of tracked tree | revert docs/example/spec delta |

## Phase 1: Foundation — pure strict module

- [x] 1.1 (T1) RED→GREEN `render_distribuido/render_config.py`: chain (env `RENDER_CONFIG_BASE` → lazy `SamanTools.entorno` w/ sys.path shim → `{base}/.saman/studio_config.json` → per-key merge `RENDER_LOCAL_CONFIG`), `validar_esquema()` accumulating ALL missing keys/types, strict policy (FileNotFoundErr→copy-example; OSError/Timeout/EIO→mount, no template advice), local-complete autonomy. AC: Resolution chain + Strict availability + Schema integrity scenarios. Dep: —. +170/0 | M
- [x] 1.2 (T2) RED→GREEN translation + gate in same module: `traducir_ruta(ruta, desde_so, hacia_so, config)`, `detectar_so_de_ruta` (longest-prefix), `_canon` (PurePosixPath), `normalizar_separadores` (PureWindowsPath), `mapa_bases`; `_gate_mount(base, timeout=3, intentos=2)` cache-free (D7). AC: Multi-OS translation scenarios; unknown prefix passes through. Dep: 1.1. +100/0 | M

## Phase 2: Orchestrator / worker refactor

- [x] 2.1 (T3) `render_distribuido.py`: delete WORKERS/BASE_MAC/BASE_LINUX/suffix argparse defaults; resolve workers/bases/suffixes from `obtener_config_efectiva()` post-parse; `ssh=f"{ssh_user}@{ssh}"`; `bin`→`nuke_exec`; `template_local(template, config)` via `traducir_ruta`; `ejecutar` explicit `env KEY='val' ...` argv, worker/`--workers` names never reach shell (D6; RED argv test). AC: Orchestrator refactor scenarios; no IPs/users in file. Dep: 1.1, 1.2. +450/0 | L
- [x] 2.2 (T4) `render_worker.py`: `setear_variables` reads TO_SUF/COMP_SUF/FROM_SUF ONLY from `os.environ`, drop `/HTLR/...` fallbacks (D6). AC: Suffix defaults scenario. Dep: 1.1. +200/0 | S

## Phase 3: Public assets, docs, tests

- [x] 3.1 (T5) `studio_config.example.json` (hostnames/DNS, no IP literals, passes strict loader), `render_distribuido/README.md` (pattern, real config path, creation steps, ACL D8 admin-WRITE/worker-READ + fallback `RENDER_LOCAL_CONFIG`, `cat` verification), `docs/ARQUITECTURA.md` ACL note (D8). AC: Example validates + No IPs + ACL documented scenarios. Dep: 1.1. +115/−5 | M
- [x] 3.2 (T6) Remaining `tests/test_render_config.py` cases (example validates, ejecutar env argv, worker env-only, gate retry cache-free) + full suite green `python3 -m pytest` (392 existing + new). Dep: 1.1–3.1. +60/0 | M

## Phase 4: Sanitized commit + spec sync

- [x] 4.1 (T7) Commit `render_distribuido/` sanitized + `tests/test_no_fuga.py` grep guard (`192\.168`|`@` → 0 across tracked files; `config_local.py` never tracked). AC: Sanitized commit scenario. Dep: 2.1, 2.2, 3.1. +30/0 | S
- [x] 4.2 (T8) Spec sync: MODIFIED delta in `specs/render-config-central/spec.md` — requirement "Public template, docs, tests, sanitized commit" + scenario "ACL documented" → admin WRITE + worker READ (D8), fallback complete `RENDER_LOCAL_CONFIG`; remove "admin-ONLY read/write" wording. AC: spec wording == D8; `admin-ONLY read/write` absent from spec. Dep: —. +7/−4 | S

Totals: +1,332 / −9 tracked lines. Effort: S < ½ session, M ½–1, L 1–1.5.