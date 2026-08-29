---
name: nuke-breakdown-gizmo
description: "Trigger: breakdown, frames breakdown, VFX breakdown, generar frames, widget frame_manager, gizmo con tabla de frames y capas, para review. Crea un .gizmo Nuke con un panel Qt (QTableWidget) que edita un JSON de frames y capas visuales (Brillo/Muzzle/Humo/Impacto/Sangre) y regenera el grafo FrameHold/Text2 -> ContactSheet al pulsar Generar. Replica el patrón del Breakdown.gizmo del proyecto HTLR."
license: Apache-2.0
metadata:
  author: "emanuel"
  version: "1.0"
---

# Nuke Breakdown Gizmo

## Activation Contract

Load when asked to build a Nuke "breakdown" / "frames breakdown" / review gizmo that shows a Qt table to edit frames + visual layers (Brillo, Muzzle, Humo, Impacto, Sangre) and that, on demand, generates the internal FrameHold/Text2 -> ContactSheet node graph from that table. Replicates the working `Breakdown.gizmo` + `frame_manager.py` pattern already built in the HTLR project. Triggers: "breakdown", "crear un gizmo de breakdown", "widget de frames para review", "generar frames".

## Hard Rules

- ALWAYS keep the Python widget as a separate module (`~/.nuke/SamanTools/frame_manager.py`) and reference it from the group via a PyCustom knob — do NOT inline hundreds of lines of Python into the `.gizmo` knobs. The Breakdown node is GLOBAL (available in any project), not project-scoped.
- The PyCustom knob (addUserKnob type 52) MUST point to a container CLASS with a `makeUI()` method that returns the widget. Nuke does NOT accept a raw widget: it instantiates the class and calls `.makeUI()`. Without `makeUI()` the panel fails silently (error: `'...' object has no attribute 'makeUI'`).
  - Knob line: `addUserKnob {52 table_ui l "" -STARTLINE T __import__('frame_manager').FrameManagerKnob()}`
- `FrameManagerKnob` must be a class like:
  ```python
  class FrameManagerKnob(object):
      def __init__(self, *args, **kwargs):
          self._nodo = None
          if args and isinstance(args[0], str):
              try: self._nodo = nuke.toNode(args[0])
              except Exception: self._nodo = None
      def makeUI(self):
          nodo = self._nodo or nuke.thisNode()
          return FrameManagerTable(nodo)
  ```
- The widget (table) subclasses `QTableWidget` directly and is the whole component: columns `Frame` + 5 layers, a spin for frame and centered checkboxes per layer. No sub-tabs, no embedded buttons (buttons live in the group as python_button type 22).
- Register the live instance by node name so group buttons can reach it: `_INSTANCES[node.name()] = self` and `@classmethod instancia(cls, node)`.
- Buttons in the group are `addUserKnob {22 ...}` (python_button) with scripts that resolve the widget, e.g.:
  ```
  from frame_manager import FrameManagerTable
  t = FrameManagerTable.instancia(nuke.thisNode())
  if t: t.agregar()
  ```

## Group Knob Contract (the group the gizmo must contain)

- `frame_data` (addUserKnob type 1, `+INVISIBLE`): JSON string = list of dicts `[{"frame": 10, "brillo": false, "muzzle": false, "humo": false, "impacto": false, "sangre": false}, ...]`. Serialized with escaped quotes/brackets.
- `table_ui` (addUserKnob type 52): the PyCustom knob above.
- Action buttons (type 22 python_button): `Agregar`, `Eliminar`, `▲` (subir), `▼` (bajar), `Generar`.
- `Desfase` (addUserKnob type 3, an integer/int knob): shifts ALL generated frames, wired into each FrameHold via `firstFrame` expression `"<frame> + parent.Desfase"`.
- `VerTexto` (addUserKnob type 6 boolean, default true): toggles the Text2 overlays via `disable "{{!parent.VerTexto}}"`.

## Internal Node Graph (default/minimal)

The `.gizmo` ships with a MINIMAL graph (no generated branches). On "Generar" the widget rebuilds it:
`Input1 -> Dot1 -> (per table row: FrameHold_Auto_N + Text_Auto_N) -> ContactSheetAuto -> Crop1 -> Reformat2 -> Output1`

- FrameHold: `name FrameHold_Auto_<N>`, `firstFrame` = expression `"<frame> + parent.Desfase"`, input from Dot1.
- Text2: `name Text_Auto_<N>`, message `"Frame: [value FrameHold_Auto_<N>.firstFrame]"`, `disable` expression `!parent.VerTexto`, `box` = `{0 0 {input.width} {input.height}}` via expressions, `xjustify left`, `yjustify top`, `font_size_toolbar 100`.
- ContactSheetAuto: inputs = number of rows; `rows`/`columns` use the sqrt/ceil expressions; `center true`, `roworder TopBottom`, `tile_color 0xff69f7ff`, `resMult` knob (0.1–2).
- Crop1 box: `{0 0 {parent.ContactSheetAuto.width} {parent.ContactSheetAuto.height}}`.

## Execution Steps

1. Ensure `~/.nuke/SamanTools/frame_manager.py` exists with `FrameManagerTable(QTableWidget)` + `FrameManagerKnob` (class with `makeUI`). If it does not exist, create it (see asset template section).
2. Create the `.gizmo` at `~/.nuke/SamanTools/nodos/Breakdown.gizmo` (global, together with Rutas/Review) with the Group knob contract above and the minimal internal graph. `python3 -m py_compile ~/.nuke/SamanTools/frame_manager.py` to validate.
3. `SamanTools/registro.py._inyectar_frame_manager()` adds `~/.nuke/SamanTools` to `sys.path` so `__import__('frame_manager')` resolves globally (menu.py already adds `~/.nuke`; the function adds the package dir).
4. Register so the node appears in the TAB/Nodes search: `registro.py.instalar()` adds a fixed "Breakdown (frames por tabla)" command under "Insertar Nodo" (menu superior SamanTools) and the TAB submenu "HTLR · Saman · Samán", inserting the global `nodos/Breakdown.gizmo` via `nuke.nodePaste`. No project scan required.
5. Verify manually in Nuke: create the node, open properties, the table renders, edit a row, press Generar, and confirm `FrameHold_Auto_N`/`Text_Auto_N`/`ContactSheetAuto` appear and `Desfase` shifts them.

## Caveats / Gotchas

- If the table "disappears", the knob `table_ui` expression is failing — almost always the `makeUI` contract (container class, not the widget directly), or the module was loaded before the fix (stale `import`); re-import with `importlib.reload(frame_manager)` and re-create the node (open knob instances do NOT re-evaluate).
- The module file lives at `~/.nuke/SamanTools/frame_manager.py` (GLOBAL, not project-scoped) and the group at `~/.nuke/SamanTools/nodos/Breakdown.gizmo`. Keep them there.
- PyCustom knob type 52 evaluates `__import__('frame_manager').FrameManagerKnob()` alive — do not depend on `__main__`.
- Nuke keyword `tags=` is NOT supported in `Menu.addCommand` on this version — never use it.

## Output Contract

Return: the `.gizmo` path, the `frame_manager.py` path, confirmation the PyCustom knob uses `FrameManagerKnob` (class with `makeUI`), the group knob contract present (frame_data/table_ui/Desfase/VerTexto/buttons), and verification steps done.

## References

- `~/.nuke/SamanTools/nodos/Breakdown.gizmo` — the global reference group this skill generalizes.
- `~/.nuke/SamanTools/frame_manager.py` — the global widget module (source of truth for the table + node rebuild).
- `/Volumes/wupm/2026/HTLR/.opencode/skills/nuke-gallery-gizmo/SKILL.md` — sibling skill; same project-level skill conventions.
- `/Users/emanuel/.nuke/SamanTools/` — bootstrap (registro.py `_inyectar_frame_manager`) and TAB registration (proyecto.py).
