# render-shot-selection Specification

## Purpose

Resolves a plan-level intent ("render shots of Capitulo 7") into the concrete comp folders of the target project's physical layout, then picks the best `.nk` version per folder by real filesystem mtime. Layouts are declarative relative patterns (never absolute paths), resolved against the config base; intent that does not exist verbatim in storage is remapped onto the project's pattern. Selection is confirmed interactively unless `--resolve-latest` is set.

## Requirements

### Requirement: Layout-driven shot resolution

ID: RC-SS-01 · Layer: Must

The system MUST resolve a plan intent into shot folder paths using the target project's declarative layout: HTLR maps to episodes `EP_n` under `COMP/`, PCF maps to sequences `PFC_SC##`, IPYD maps to numeric episodes `101..106`. An intent path that does not exist in storage (e.g. `2VFX/Capitulo_7`) MUST be remapped to the project's real pattern instead of failing on the literal path. Layout patterns MUST be relative (no absolute roots, no IP literals, no `@`-user tokens) and MUST pass the `test_no_fuga` scan. Project roots MUST resolve from `bases_por_so` only for enabled `proyectos`.

#### Scenario: HTLR episode

- GIVEN `--proyecto HTLR` and intent "Capitulo 7"
- WHEN shot folders are resolved
- THEN folders under the HTLR base's `COMP/EP_07/` are listed

#### Scenario: Intent path does not exist

- GIVEN intent `2VFX/Capitulo_7` absent in storage
- WHEN resolved for HTLR
- THEN the intent is remapped to `EP_07` and resolution succeeds

#### Scenario: PCF sequence

- GIVEN `--proyecto PCF` and intent "SC13"
- WHEN shot folders are resolved
- THEN folders under `COMP/PFC_SC13/` are listed

#### Scenario: IPYD episode

- GIVEN `--proyecto IPYD` and intent "104"
- WHEN shot folders are resolved
- THEN IPYD episode `104` folders (naming `IPYD_104_*_COMP_SAMAN_SE`) are listed

#### Scenario: No-fuga layout

- GIVEN the layout data module
- WHEN scanned for IP literals, `@` followed by a letter, or absolute paths
- THEN `test_no_fuga` reports zero matches

### Requirement: mtime-based comp version selection

ID: RC-SS-02 · Layer: Must

`mejor_version_comp(plan_dir)` MUST select the `.nk` with the greatest real filesystem mtime among the folder's `_comp_SAMAN_`-pattern versions; the `_V\d+` number MUST NOT be the selection key. Selection MUST ignore `.nk~`, `.autosave` and temporary files. On equal mtime, the highest `_V\d+` MUST win as tie-break. mtime MUST be measured on the orchestrator host (iMac), never on render workers, because LucidLink collapses `ctime`/`birthtime`.

#### Scenario: Newer mtime beats higher version number

- GIVEN `v001` touched today and `v015` approved a month ago
- WHEN `mejor_version_comp` selects
- THEN `v001` is selected
- AND the artist is offered [Usar v015] as one-click override

#### Scenario: Autosave and temp ignored

- GIVEN `plan_comp_SAMAN_v003.nk~`, `plan_comp_SAMAN_v003.nk.autosave` and `plan_comp_SAMAN_v002.nk`
- WHEN candidates are listed
- THEN only `plan_comp_SAMAN_v002.nk` qualifies

#### Scenario: mtime tie-break

- GIVEN two versions with identical mtime, `_V005` and `_V012`
- WHEN selection runs
- THEN `_V012` wins

### Requirement: Selection confirmation and CLI flags

ID: RC-SS-03 · Layer: Should

The system SHOULD present selected comps for confirmation ([Confirmar] / [Ver lista y desmarcar]) before rendering. `--resolve-latest` MUST pick the best version per folder without confirmation. `--proyecto` MUST default to HTLR with an explicit notice; `--comp-dir` MUST target a single comp folder directly. A folder with no qualifying `.nk` MUST abort with a clear message, never silently skip.

#### Scenario: Deselect before confirm

- GIVEN a selection list of 46 comps (15 with multiple versions)
- WHEN the artist uses [Ver lista y desmarcar]
- THEN a subset is confirmed for rendering

#### Scenario: Resolve-latest skips confirmation

- GIVEN `--resolve-latest`
- WHEN selection runs
- THEN the best version per folder is chosen with no prompt

#### Scenario: No comp found

- GIVEN a target folder with no `.nk` files
- WHEN selection runs
- THEN the run aborts and names the folder