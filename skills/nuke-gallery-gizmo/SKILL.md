---
name: nuke-gallery-gizmo
description: "Trigger: galería de assets, gallery gizmo, contact sheet, construir galería de previsualización de assets de GLOBAL_ASSETS, visión general de footage de compra. Genera un .gizmo Nuke estilo MuzzleHTLR con ContactSheets por categoría, selector de elemento, grid general y nombres, a partir de una carpeta de assets del proyecto HTLR."
license: Apache-2.0
metadata:
  author: "emanuel"
  version: "1.0"
---

# Nuke Gallery Gizmo

## Activation Contract

Load when asked to build a Nuke shot-selection gallery or contact sheet from a folder of purchased stock footage / VFX assets (ActionVFX, etc.), especially "galería de assets", "gallery gizmo", "contact sheet de compra", or generalizing the existing `MuzzleHTLR.gizmo`. Produces a `.gizmo` with per-category ContactSheets, an element selector, a full grid, and optional file-name labels.

## Hard Rules

- ALWAYS generate the `.gizmo` by running `python3 <skill>/assets/build_gallery_gizmo.py <assets_dir>` with arguments matched to the asset layout. Never hand-write a large gallery node graph.
- Reproduce the original MuzzleHTLR interaction contract faithfully:
  - Knobs: `categoria` (menu of categories + `"Todos (Grid General)"`), one `elem_<cat>` menu per category, hidden `show_grid`, `boolean` = "Ver Nombres", `resMult`.
  - Per asset: Read → Grade → Premult → Text2 (Text2 shows the asset file name).
  - ContactSheet per category + ContactSheet ALL; element Switch per category; main Switch `categoria*2 + show_grid`; final Output.
- Use dynamic paths: file line MUST be `\[python \{PYTHON_COMP\}]/GLOBAL_ASSETS/<rel>/<file>` — never absolute paths. The generator does this automatically. Note Nuke escapes BOTH brackets and braces when serializing (`\{PYTHON_COMP\}`); the generator's `esc_nuke()` produces this canon. When spot-checking, strip the literal prefix `\[python \{PYTHON_COMP\}]/` before validating with `ls`.
- Detect real resolution per asset with `ffprobe`; if the generator's default fallback (3840x2160) is used, verify at least one sample with `ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0:s=x <file>`.
- Video Reads follow the project frame convention (same as `nuke-project-clone`): `file_type mov`, `first 1`, `last`/`origlast` = real frame count of the clip, `origset true`. The generator probes real frames with ffprobe (`nb_frames`, decoding with `-count_frames` as fallback) and writes these knobs on every video Read — never let a video inherit timecode or start at 1001. The `first 1` is written deliberately as a defense against clips with timecode ≠ 1, even though Nuke omits it when re-saving. Video Reads also get `colorspace color_picking` when `--colorspace` is active (default), which is the `--no-colorspace` opt-out.
- `mov64_prraw_plugin Standard` may appear on video Reads after Nuke re-saves — that is normal and version-dependent; the generator does not need to produce it.
- Still images keep the existing `origset true`; do not add frame-range knobs unless the generator does explicitly.
- Between `gal_main` and the final Output the generator places a chained Crop → Reformat → FrameHold → Output (sequential nodes, no intermediate pushes; first push is `push $gmain` before Crop).
- The FrameHold is exposed in the "Visualización" tab through native link knobs (addUserKnob type 41) that surface the actual FrameHold knob and its methods — NOT a copy knob with an expression:
  - `Espacio` (type 26, `T "   "`) — thin separator.
  - `firstFrame` (type 41, label "First Frame", `T FrameHold1.firstFrame`) — links the group knob to the FrameHold's frame knob.
  - `setToCurrentFrame` (type 41, label "Set to Current Frame", `-STARTLINE`, `T FrameHold1.setToCurrentFrame`) — expose the FrameHold's "Set to Current Frame" button.
  - `use_frame` (boolean, label "Usar Frame Hold", default `false`) — the check that toggles the freeze; starts disabled so clips play in motion by default.
- The FrameHold itself uses the project's clean serialization: `firstFrame <default>` (25, a direct value, no expression), `name FrameHold1`, `xpos -978`, `ypos 394`, `disable {{!parent.use_frame}}` (same pattern as Text2's `disable {{!parent.boolean}}`); no `path_mask_group`, no `selected`.

## Decision Gates

| Asset layout | Generator flags |
|---|---|
| Subfolders = categories (e.g. `MUZZLE FLASHES VOL 1/.../{Angled,Front,Side}`) | default |
| Flat folder, category appears in filename (e.g. `Blood_Splatter_Front_3_1839_2K.mov`) | `--split-by-token` |
| Flat folder, category = multi-word prefix of the name (e.g. `Continuous_Landing_1_0611_2K.mov` → `Continuous_Landing`, `Sparks_Landing_High_Angle_1_0604_2K.mov` → `Sparks_Landing_High_Angle`, "ELECTRICAL SPARKS VOL. 1") | `--split-by-prefix` |
| Whole collection root with mixed `.mov` | `--split-by-token` |
| Still images (PNG/exr) with alpha | default; keep `--colorspace color_picking` |
| Exact output path / group name | `--out`, `--name` |

## Execution Steps

1. Inspect the target: run `find <assets_dir> -maxdepth 2` to see whether categories are subfolders or filename tokens; count assets and check extensions.
2. Run the generator with matching flags:
   `python3 <skill>/assets/build_gallery_gizmo.py <assets_dir> [--split-by-token|--split-by-prefix] [--name <Grupo>] [--out <ruta>.gizmo]`
   For flat folders whose category is a multi-word filename prefix (before the first number, e.g. `Sparks_Landing_High_Angle`), use `--split-by-prefix`; if both flags are passed, `--split-by-prefix` wins.
   Default output: `COMP/Scripts/<slug>.gizmo`.
3. Verify output: grep for `name gal_cs_` (one per category + `gal_cs_all`), `name gal_sw_` (one per category), one `gal_main`, and `Read {` count == asset count.
4. Spot-check one `file "..."` line: must start `\[python \{PYTHON_COMP\}]/GLOBAL_ASSETS/` and point to an existing relative path (strip the literal `\[python \{PYTHON_COMP\}]/` prefix and test with `ls`).
5. For video assets, verify every Read has `first 1` (count == `Read {` count) and `file_type mov`, no `last 1001` (timecode leak), and spot-check `last`/`origlast` against real ffprobe frame counts.
6. If the user wants to browse while deciding which assets to buy, copy a sample/representative frame to PNG alongside (only when the source is video and a still thumbnail is desired).

## Output Contract

Return: the `.gizmo` path, the categories detected with per-category asset counts, the total asset count, the resolution detected for the first probe, the flags used, and a confirmation that dynamic `GLOBAL_ASSETS` paths and `gal_main`/`gal_cs_all` nodes are present.

## Re-serialization note

Re-saving the group with `nuke.thisNode().writeToFile()` is normal and safe: Nuke reorders nodes by `xpos`, re-escapes braces, bumps Read `version` to 2, adds `mov64_prraw_plugin Standard` on video Reads, and drops `first 1` (kept by the generator as a timecode defense). None of this breaks the gizmo or the generator contract.

## References

- `assets/build_gallery_gizmo.py` — the generator (single source of truth for node graph + connection order: pushes precede their consuming node; last push = input 0).
- `/Volumes/wupm/2026/HTLR/COMP/Scripts/MuzzleHTLR.gizmo` — the reference gallery the skill generalizes.
- `/Volumes/wupm/2026/HTLR/COMP/GLOBAL_ASSETS/` — asset source root.
- `/Volumes/wupm/2026/HTLR/.opencode/skills/nuke-project-clone/SKILL.md` — sibling skill; same dynamic-path and format conventions.