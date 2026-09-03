# render-qc-plate Specification

## Purpose

Pre-render QC gate ("Regla de Oro"): locate the reference plate in the project's layout, deep-probe it with ffprobe, compare against the comp's Root and delivery template with one-click decisions per discrepancy, and report + abort unless `--force-qc`. The delivery node is validated against the plate and overwritten if different.

## Requirements

### Requirement: Plate localization

ID: RC-QC-01 · Layer: Must

The system MUST locate the plate in the target project's layout by taking the most recent date folder (HTLR `TO_VFX/EP_n/YYYYMMDD/`, IPYD dates with optional `-2` suffix e.g. `20260628-2`, PCF `FROM_VFX/PFC_SC##/YYYYMMDD/`). With several dates, the most recent MUST win by default and the artist MUST get [Usar más reciente] / [Usar otra] one-click override. An unmatched plate (broken naming) MUST follow the naming decision path, never silently pair.

#### Scenario: Most recent date wins

- GIVEN IPYD plates `20260627` and `20260628-2`
- WHEN the plate is localized
- THEN `20260628-2` is selected

#### Scenario: Override selects older plate

- GIVEN two date folders and artist intent on the older delivery
- WHEN [Usar otra] is chosen
- THEN the older date is used as plate

### Requirement: Deep ffprobe of the plate

ID: RC-QC-02 · Layer: Must

The system MUST probe the plate with ffprobe and extract codec (ProRes 4444), bit depth (10-bit), colorspace, resolution, fps and frame count (from `nb_frames`/`r_frame_rate`). Probe or parse failure MUST abort with a clear message, never a silent default. Parsing MUST be testable from a fixture without Nuke.

#### Scenario: ProRes fixture parse

- GIVEN an ffprobe fixture: ProRes 4444, 10-bit, 1920x1080, 23.976 fps, 1665 frames
- WHEN the probe is parsed
- THEN codec, bit depth, colorspace, resolution, fps and frames match the fixture

#### Scenario: Probe failure

- GIVEN a missing or unreadable plate file
- WHEN the probe runs
- THEN the QC gate aborts and names the missing path

### Requirement: Comparison vs Root and delivery template

ID: RC-QC-03 · Layer: Must

The system MUST compare plate vs comp Root (fps, format, first–last frames) and vs the delivery template. A delivery node differing from the plate in frames, fps or resolution MUST abort before render unless `--force-qc`, and MUST be rewritten to the plate's specs. FPS 24 vs 23.976 MUST offer [Forzar 23.976] / [Cancelar]; broken naming MUST offer [Validar solo duración] / [Abortar]. Drift on PREVIEW nodes only MUST be a report WARNING, not an abort.

#### Scenario: FPS mismatch aborts without force

- GIVEN comp at 24 fps and plate at 23.976 fps
- WHEN the gate runs without `--force-qc`
- THEN the run aborts and offers [Forzar 23.976]
- AND with `--force-qc` it proceeds

#### Scenario: Preview drift warns only

- GIVEN REC709 EP_108 at 1558 frames vs plate at 1665
- WHEN the gate runs
- THEN the report warns and the run continues without abort

#### Scenario: Naming broken

- GIVEN a plate name that cannot be paired to any write node by naming
- WHEN the gate runs
- THEN [Validar solo duración] proceeds on duration only, [Abortar] stops

#### Scenario: Delivery node overwritten

- GIVEN delivery EXR node at 1920x1080/24fps vs plate 2048x1156/23.976
- WHEN the alignment runs
- THEN the delivery node's format and fps are overwritten to the plate's values

### Requirement: Gate report and force

ID: RC-QC-04 · Layer: Must

The QC gate MUST be ON by default, emitting a report of all discrepancies and aborting unless `--force-qc` is passed; `--force-qc` MUST proceed despite discrepancies. Legacy runs without the new flags MUST NOT trigger the gate.

#### Scenario: Report emitted with force

- GIVEN discrepancies and `--force-qc`
- WHEN the gate runs
- THEN the report lists the discrepancies and the render proceeds

#### Scenario: Legacy run unaffected

- GIVEN a run with `--comp` and no new flags
- WHEN QC would run
- THEN the legacy path behaves as before (no gate)