# render-multinodo Specification

## Purpose

Discovers the real Write nodes of a comp (DELIVERY_EXR, DELIVERY_DWG, REVIEW_REC709, SBS_REC709), applies per-node existence policy (EXR per frame, MOV per file), renders CALIB/PLAN only on the delivery EXR node, piggybacks previews on the same render respecting `use_limit`, and can force EXR sequence output conserving duration and resolution. User-facing labels map to real node names (`DELIVERY_*`, `REVIEW_REC709`, `SBS_*`) — never the literals "delivery", "preview" or "side by side".

## Requirements

### Requirement: Real Write-node discovery

ID: RC-MN-01 · Layer: Must

The system MUST discover the comp's real Write nodes by name among `DELIVERY_EXR`, `DELIVERY_DWG`, `REVIEW_REC709`, `SBS_REC709`. `--wnodes` MUST filter which discovered nodes participate in the run. Friendly labels ("delivery", "preview", "side by side") MUST NOT be used as node names; the mapping MUST stay on real node names.

#### Scenario: Nodes discovered by real name

- GIVEN a comp with `DELIVERY_EXR`, `REVIEW_REC709`, `SBS_REC709`
- WHEN discovery runs
- THEN exactly those nodes are found and `--wnodes` filters them

#### Scenario: No friendly-name leakage

- GIVEN the node mapping
- WHEN it is scanned for "delivery"/"preview"/"side by side" as node addresses
- THEN zero matches; all addresses are `DELIVERY_*`/`REVIEW_REC709`/`SBS_*`

### Requirement: Per-node existence policy

ID: RC-MN-02 · Layer: Must

The system MUST apply existence policy per node type: EXR outputs are frame sequences (existence checked per frame), MOV outputs are single files (existence checked per file). CALIB/PLAN rendering MUST run only on the delivery EXR node. Previews MUST piggyback on the same render as their parent delivery node, respecting the existing `use_limit`.

#### Scenario: EXR per-frame policy

- GIVEN DELIVERY_EXR expected to cover 1665 frames with 900 existing
- WHEN existence is checked
- THEN the 765 missing frames are reported for render

#### Scenario: MOV per-file policy

- GIVEN DELIVERY_DWG expected file absent on disk
- WHEN existence is checked
- THEN the file is scheduled for render

#### Scenario: CALIB/PLAN only on delivery EXR

- GIVEN CALIB/PLAN requested with multiple Write nodes present
- WHEN render scope is computed
- THEN CALIB/PLAN is added only to DELIVERY_EXR

#### Scenario: Preview piggyback with use_limit

- GIVEN REVIEW_REC709 flagged as preview of DELIVERY_EXR
- WHEN render runs
- THEN REVIEW_REC709 renders in the same pass and `use_limit` holds

### Requirement: Forced EXR sequence output

ID: RC-MN-03 · Layer: Should

The system SHOULD offer an option to force the delivery node's output to an EXR sequence; forcing MUST conserve the node's duration and resolution.

#### Scenario: Force sequence conserves specs

- GIVEN a delivery node currently outputting a single file
- WHEN the force-sequence option is applied
- THEN the node outputs an EXR sequence with the same duration and resolution