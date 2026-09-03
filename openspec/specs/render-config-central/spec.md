# render-config-central Specification

## Purpose

Central infrastructure config for the `render_distribuido/` orchestrator: workers, per-OS bases and suffixes resolve from `{base}/.saman/studio_config.json` (vfxflow_config pattern: entorno base → `.saman` JSON → gitignored `config_local.py`) with a STRICT policy: unavailable or schema-invalid config aborts with creation instructions, never silent defaults. Path translation across declared bases generalizes cross-OS frame detection.

## Requirements

### Requirement: Config resolution chain

Effective config MUST resolve as base from `entorno.primera_ruta_disponible()` (lazy import; MAY be env-overridable) → `{base}/.saman/studio_config.json` → gitignored `RENDER_LOCAL_CONFIG` in `config_local.py`; later sources MUST override per key. A schema-complete local dict SHALL waive the disk: try disk first; missing or network-failed disk plus complete local MUST use local; incomplete or absent local MUST abort per the strict policy. Strict policy MUST apply only when no source yields a complete schema.

#### Scenario: Happy path merge

- GIVEN valid base, valid JSON and local `RENDER_LOCAL_CONFIG`
- WHEN effective config requested
- THEN local keys override JSON keys

#### Scenario: Base override

- GIVEN an env base override pointing to valid JSON
- WHEN effective config requested
- THEN the override base wins over `entorno.primera_ruta_disponible()`

#### Scenario: Local complete, no disk

- GIVEN schema-complete local dict and absent/broken disk JSON
- WHEN effective config requested
- THEN local values resolve with no abort

#### Scenario: Local incomplete, no disk

- GIVEN incomplete or absent local dict and absent disk JSON
- WHEN effective config requested
- THEN the load aborts with the missing-keys diagnosis

### Requirement: Strict availability policy

Without a base, or absent/unreadable/invalid JSON with no complete local source, the load MUST raise `SystemExit`; no default MAY replace it. `FileNotFoundError` (or file absent after a mount check) MUST say the config is missing, name the target JSON, and instruct copying `studio_config.example.json` to `{base}/.saman/studio_config.json`. `OSError`/`TimeoutError` (LucidLink hung, mount lost, EIO) MUST emit an explicit connection-or-mount failure before aborting and MUST NOT suggest copying the template. The check MAY gate on `entorno.estado_unidad` with a 3s timeout, like `_verificar_ruta`.

#### Scenario: No config available

- GIVEN no base or missing/invalid JSON
- WHEN config loaded
- THEN `SystemExit` names target path and suggests copying `studio_config.example.json`
- AND no versioned defaults apply

#### Scenario: Missing file

- GIVEN `FileNotFoundError` on the disk JSON
- WHEN config loaded
- THEN the message says the config is missing and names the target JSON
- AND instructs copying `studio_config.example.json`

#### Scenario: Mount dead

- GIVEN `OSError`/`TimeoutError`/EIO (LucidLink hung)
- WHEN config loaded
- THEN an explicit connection-or-mount failure precedes the abort
- AND no copy-template instruction is shown

### Requirement: Schema integrity validation

ID: RC-CN-02 · Layer: Must

The load MUST validate the schema before use: top-level `bases_por_so` (mapping OS→path), `workers` (list), `sufijos` (mapping); each worker MUST have `nombre`, `ssh` (host or None), `ssh_user`, `nuke_exec`, `base`, `lc_all`. When present, top-level `proyectos` (project enablement, additive) MUST be a mapping whose values are booleans; its absence MUST NOT fail validation so legacy configs keep loading. Validation MUST accumulate ALL missing keys and type errors into one `SystemExit` listing each failure with repair guidance.

#### Scenario: Multiple missing keys

- GIVEN JSON missing `workers` and worker lacking `nuke_exec`
- WHEN config loaded
- THEN one `SystemExit` lists both failures
- AND names each key path

#### Scenario: Wrong type

- GIVEN `bases_por_so` as a list instead of a mapping
- WHEN config loaded
- THEN `SystemExit` states the expected type

#### Scenario: Invalid proyectos entry

- GIVEN `proyectos` whose value for `PCF` is a string instead of a boolean
- WHEN config loaded
- THEN `SystemExit` states the expected boolean type

#### Scenario: Proyectos absent is valid

- GIVEN a legacy config without `proyectos`
- WHEN config loaded
- THEN validation passes; `proyectos` resolves to empty

### Requirement: Multi-OS path translation

The system MUST expose a translation utility whose prefixes derive from `bases_por_so`, supporting ANY declared pair (e.g. `W:\wupm`, `/media/wupm`, `/Volumes/wupm`); paths outside declared prefixes MUST pass through unchanged. Translation MUST normalize separators toward the target OS, not only the prefix: POSIX targets MUST yield only `/`; Windows targets MUST use `\` (MAY via `os.path.normpath`, `PurePosixPath`, `PureWindowsPath`). Existing-frame detection MUST translate worker templates through it instead of the hardcoded `/mnt`↔`/Volumes` pair.

#### Scenario: Cross-OS translation

- GIVEN darwin `/Volumes/wupm` and windows `W:\wupm` declared
- WHEN template under `/Volumes/wupm/2026/...` translates to windows base
- THEN result starts with `W:\wupm\2026\`

#### Scenario: Unknown prefix

- GIVEN a path prefix not declared in `bases_por_so`
- WHEN translated
- THEN the path is unchanged

#### Scenario: Windows to POSIX separators

- GIVEN `W:\wupm` maps to `/media/wupm` (POSIX target)
- WHEN `W:\wupm\2026\PCF\TO_VFX\x.nk` is translated
- THEN the result is `/media/wupm/2026/PCF/TO_VFX/x.nk`
- AND it contains no `\`

#### Scenario: POSIX to Windows separators

- GIVEN `/media/wupm` maps to `W:\wupm` (Windows target)
- WHEN a Linux path is translated
- THEN the result uses `\` throughout

### Requirement: Orchestrator refactor

`render_distribuido.py` MUST read workers, per-OS bases and suffix defaults from config, and MUST NOT hardcode IPs/users, `BASE_MAC`/`BASE_LINUX`, or suffix argparse defaults; CLI flags MAY still override suffixes per run. `render_worker.py` MUST take suffix defaults from config-provided env, not literal `/HTLR/...` fallbacks.

#### Scenario: Workers from config

- GIVEN config with two workers
- WHEN orchestrator selects workers
- THEN exactly those two are active (`--workers` filters)

#### Scenario: Suffix defaults from config

- GIVEN `sufijos.TO_VFX` equals `/TO/`
- WHEN running without `--to-suf`
- THEN worker env `TO_SUF` equals `/TO/`

### Requirement: Public template, docs, tests, sanitized commit

ID: RC-CN-05 · Layer: Must

The change MUST ship `studio_config.example.json` (no real data, schema-conformant, passing loader validation) and a README documenting pattern, real config location, ACL (admin WRITE + worker READ on `{base}/.saman/studio_config.json` via the workers' `ssh_user`, D8; fallback: a node that cannot read the JSON holds the complete `RENDER_LOCAL_CONFIG` in `config_local.py`) and creation steps. Template and README MUST use hostnames/DNS (e.g. `vfxserver`, `macserver.studio.local`) for hosts; IPs MAY appear only as fallback; the public template MUST NOT contain IP literals. Tests MUST run without Nuke via the existing stub, covering env base override, local precedence, strict abort, missing keys, wrong type, translation per OS combination, example validation. `render_distribuido/` MUST be committed sanitized: no real IPs, users or hosts tracked. Semantic roles (PLATE, DELIVERY, PREVIEW, SBS) MUST stay fixed in code as the stable domain; the physical folder layout is NOT fixed — each project declares its own relative layout patterns as DATA, resolved from `bases_por_so` plus enabled `proyectos`, and `test_no_fuga` MUST prove the layout data contains no absolute paths, IP literals or `@`-user tokens. Sanitizing versioned gizmos/skills is out of scope.

#### Scenario: Example validates

- GIVEN `studio_config.example.json` including a `proyectos` map
- WHEN validated through the strict loader
- THEN no `SystemExit` is raised

#### Scenario: Sanitized commit

- GIVEN the commit adding layout data
- WHEN tracked files are searched for `192.168` or `@`
- THEN zero matches

#### Scenario: No IPs in public template

- GIVEN `studio_config.example.json`
- WHEN scanned for IP literals
- THEN zero matches; worker hosts are hostnames

#### Scenario: ACL documented

- GIVEN the README
- WHEN read
- THEN it states admin WRITE + worker READ (workers' `ssh_user`) on `{base}/.saman/studio_config.json` — D8, infra not secret
- AND it documents the complete `RENDER_LOCAL_CONFIG` fallback for nodes that cannot read the JSON

#### Scenario: Layout data is relative

- GIVEN the per-project layout patterns
- WHEN scanned for absolute roots, IP literals or `@`+letter tokens
- THEN zero matches (`test_no_fuga` green)