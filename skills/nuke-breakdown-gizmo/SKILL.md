---
name: nuke-breakdown-gizmo
description: "Trigger: breakdown, frames breakdown, VFX breakdown, generar frames, widget frame_manager, gizmo con tabla de frames y capas, para review. Crea un .gizmo Nuke con un panel Qt (QTableWidget) que edita knobs Int nativos de frames y capas visuales (Brillo/Muzzle/Humo/Impacto/Sangre) y reconcilia el grafo FrameHold/Text2 -> ContactSheet al pulsar Generar. Replica el patrón del Breakdown.gizmo del proyecto HTLR."
license: Apache-2.0
metadata:
  author: "emanuel"
  version: "3.0"
---

# Nuke Breakdown Gizmo

## Activation Contract

Load when asked to build a Nuke "breakdown" / "frames breakdown" / review gizmo that shows a Qt table to edit frames + visual layers (Brillo, Muzzle, Humo, Impacto, Sangre) and that, on demand, reconciles the internal FrameHold/Text2 -> ContactSheet node graph from that data. Replicates the working `Breakdown.gizmo` + `frame_manager.py` pattern already built in the HTLR project. Triggers: "breakdown", "crear un gizmo de breakdown", "widget de frames para review", "generar frames".

## Hard Rules

- ALWAYS keep the Python split in two modules inside `SamanTools/`: `breakdown_datos.py` (lógica pura + I/O de knobs, sin Qt ni `nuke` importado) y `frame_manager.py` (widget PySide y contenedor del knob PyCustom). La lógica de datos separada es lo que permite probarla con pytest fuera de Nuke. NUNCA inline Python en los knobs del `.gizmo`. El nodo Breakdown es GLOBAL (disponible en cualquier proyecto), no por proyecto.
- Storage TIPADO, no JSON: knobs `Int` (`addUserKnob {3}`, `nuke.Int_Knob`) por fila. El knob string `frame_data` queda solo como fuente legacy para migrar una vez.
- El PyCustom knob (addUserKnob type 52) MUST point to a container CLASS with a `makeUI()` method that returns the widget. Nuke does NOT accept a raw widget: it instantiates the class and calls `.makeUI()`. Without `makeUI()` the panel fails silently (error: `'...' object has no attribute 'makeUI'`).
  - Knob line: `addUserKnob {52 table_ui l "" -STARTLINE T __import__('frame_manager').FrameManagerKnob()}`
- `FrameManagerKnob` must stay a class with `makeUI()`:
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
- The widget subclasses `QTableWidget` directly and is the whole component: columns `Frame` + 5 layers, a spin for frame and centered checkboxes per layer. No sub-tabs, no embedded buttons (buttons live in the group as python_button type 22).
- Register the live instance by node name so group buttons can reach it: `_INSTANCES[node.name()] = self` y `@classmethod instancia(cls, node)`. MANTENER ese método y los nombres `agregar/eliminar/subir/bajar/generar`: comps viejos guardan el script de los botones con esa llamada.
- Buttons in the group are `addUserKnob {22 ...}` (python_button) with scripts that resolve the widget, e.g.:
  ```
  from frame_manager import FrameManagerTable
  t = FrameManagerTable.instancia(nuke.thisNode())
  if t: t.generar()
  ```

## Knob types: qué sobrevive y qué no (verificado en Nuke 17.1v3)

Antes de elegir un knob para storage, verificar el round-trip save/load. Lo medido:

- `nuke.Table_Knob` (ID 63) **no existe** en la API Python: no hay tabla nativa, el `QTableWidget` en el knob 52 es la única vía de UI.
- `nuke.Bitmask_Knob` **no sobrevive**: serializa como `addUserKnob {4 ... M {...}}` y al recargar vuelve como `Enumeration_Knob` (pierde la multi-selección). Prohibido como storage.
- `nuke.Array_Knob` crea un array de floats de tamaño fijo: `resize()` no surte efecto y solo serializa el primer valor (`{78 ... n 1}`). Prohibido para N frames.
- Sí sobreviven: `String_Knob` (`{1}`), `Int_Knob` (`{3}`), `Enumeration_Knob` (`{4 name l Label M {a b c}}`), `Boolean_Knob` (`{6}`), `Double_Knob` (`{7}`), `BBox_Knob` (`{15}` + `name {0 0 100 50}`), `File_Knob` (`{2}`), `Text_Knob` (`{26}`), `Tab_Knob` (`{20}`).
- Un knob marcado `+INVISIBLE` en el `.gizmo` persiste su valor entre save/load aunque el artista no lo vea (verificado: `F_1 42` → 42).

## Group Knob Contract (the group the gizmo must contain)

Storage tipado, todo `+INVISIBLE` y al final del panel:

- `N` (`addUserKnob {3}`, Int): cantidad de filas, 1..`POOL`.
- `F_<i>` (`{3}`, Int): frame de la fila `i`.
- `L_<i>` (`{3}`, Int): máscara de tildes de la fila `i`. El bit de cada columna es `1 << (slot - 1)` (hasta 8 columnas, máscara máxima 255).
- `TXT` (`addUserKnob {1}`, String, `+INVISIBLE`): valores de las columnas de texto y número, `{fila: {slot: valor}}` en JSON. **Tiene que ser tipo 1 (String)**: declarado como `{3}` Nuke lo crea Int y `setValue` revienta con `expecting a float, str found`. Se escribe al confirmar una celda (temporizador de 350 ms), nunca por tecla.
- `frame_data` (`addUserKnob {1}`, `+INVISIBLE`): JSON legacy. Se lee SOLO para migrar. Default vacío: un nodo nuevo no migra nada y conserva las columnas de ejemplo.
- `datos_ver` (`addUserKnob {3}`, `+INVISIBLE`, **sin** línea de valor): marca de versión (`VERSION_DATOS = 2`). Si el `.gizmo` shipea `datos_ver 2`, un comp del gizmo original arranca creyéndose migrado y sus filas nunca se vuelcan. Nunca le pongas default.
- Defaults de fila SÍ (`N 3`, `F_1 10`, `F_2 20`, `F_3 30`, `L_2 1`): así un nodo nuevo muestra filas de ejemplo. Un comp viejo con la tabla vacía lo normaliza la migración (que reescribe las filas aunque vengan vacías), no la ausencia de defaults.
- `POOL = 32` en `breakdown_datos.py` y 32 pares `F_<i>`/`L_<i>` declarados en el `.gizmo`. Si cambia uno, cambia el otro (hay test).

UI visible:

- `table_ui` (addUserKnob type 52): el PyCustom knob del widget.
- Action buttons (type 22 python_button): `Agregar`, `Eliminar`, `▲` (subir), `▼` (bajar), `Generar`.
- `Desfase` (addUserKnob type 3, Int): shifts ALL generated frames, wired into each FrameHold via `firstFrame` expression `"<frame> + parent.Desfase"`.
- `VerTexto` (addUserKnob type 6 boolean, default true): toggles the Text2 overlays via `disable "{{!parent.VerTexto}}"`.

## Pestaña Columnas (columnas configurables)

Segunda pestaña del panel, nativa, sin diálogos. Particiona los knobs que vienen después, así que se declara **al final** del bloque de knobs:

- `Cantidad` (`addUserKnob {3}`, Int, `R 0 8`): cuántas columnas tiene la tabla además de `Frame`.
- `Col_<i>_nombre` (`{1}`, String) y `Col_<i>_tipo` (`{4 ... M {Tilde Texto Numero}}`) para `i` en 1..8.
- `Aplicar_columnas` (type 22): llama a `frame_manager.aplicar_columnas(nodo)`, que relee la configuración y reconstruye la tabla si el panel está abierto. Toda acción de la tabla también relee la configuración.
- Defaults del `.gizmo`: `Cantidad 2`, columna 1 `Muzzle`/`Tilde`, columna 2 `Nota`/`Texto` (así se ven los dos tipos de entrada).

Reglas de las columnas:

- `Frame` es fija, siempre la primera: no se configura ni se renombra.
- Un cambio de tipo **no borra datos**: el valor queda oculto en su storage (máscara para tilde, `TXT` para texto/número) y reaparece si se vuelve al tipo anterior. No convertir valores: una conversión `tilde → texto` inventaría contenido.
- Celda de texto/número: `escribir_celda` reescribe `TXT` entero pero sólo cuando se confirma la celda, y omite los vacíos. Un número inválido revierte la celda al valor guardado.
- Tildes: `escribir_celda` toca únicamente `L_<i>`.

## Internal Node Graph and generation

The graph is: `Input1 -> Dot1 -> (per fila: FrameHold_Auto_N + Text_Auto_N) -> ContactSheetAuto -> Crop1 -> Reformat2 -> Output1`. El `.gizmo` shipea 3 ramas de ejemplo (frames 10/20/30) igual que el default de `N` y `F_<i>`; `L_2 1` marca la columna 1 del ejemplo. Las columnas **no** intervienen en la generación: son anotación.

`generar()` **reconcilia**, no reconstruye:

1. `datos.leer_filas(nodo)` (migrando el legacy si hace falta).
2. `datos.plan_reconciliacion(total, _ramas_existentes())` → `reusar`, `crear`, `sobrantes`.
3. Borra solo los sobrantes, limpia intrusos acotado por `pparent()` y recorta las entradas del ContactSheet.
4. Sincroniza cada rama: crea si falta, y escribe cada knob solo si el valor difiere.
5. `_configurar_contactsheet`: `tile_color 0xff69f7ff`, `center true`, `roworder TopBottom`, grilla con `datos.grilla(total)` y `width`/`height` = `input.width*columns*resMult` / `input.height*rows*resMult`.

Reglas duras de la generación:

- `migrar_legacy` se llama antes de leer filas, tanto en `cargar_datos` como en `sincronizar_grafo`: un comp viejo genera filas de verdad aunque nadie abra el panel.
- Migración con más filas que `POOL`: se migran las primeras `POOL`, el JSON original se conserva intacto como respaldo y `legacy_excedente(nodo)` devuelve cuántas quedaron fuera. El widget avisa con `nuke.message`. Nada se pierde en silencio.
- `resMult` se crea si falta y **nunca** se reescribe: el valor del artista sobrevive a cada Generar.
- `box`, `xjustify` y `yjustify` del Text2 se fijan solo al crear la rama, para no pisar ajustes manuales.
- `ContactSheet` no tiene knob `inputs`: el número de entradas lo fija la última conexión. Para encoger hay que desconectar desde el final (`setInput(inputs()-1, None)`); crecer lo hace `setInput` solo.
- `Array_Knob` no expone `expression()`: la expresión vigente se lee de `toScript()`, que para un knob animado es `{"<expr>"}`.
- Para saber si un nodo pertenece al grupo usá `parent()`. **`pparent()` no existe** en Nuke 17.1: la versión anterior lo llamaba dentro de un `try/except Exception`, la excepción se tragaba y la limpieza no borraba nunca nada. `_padre()` prueba ambas y no se come errores silenciosos.
- Todo envuelto en `nuke.Undo()` sin argumentos de nombre.

## Execution Steps

1. `SamanTools/breakdown_datos.py` y `SamanTools/frame_manager.py` existen y `python3 -m py_compile` pasa en ambos.
2. El `.gizmo` en `SamanTools/nodos/Breakdown.gizmo` (global, junto a Rutas/Review) con el knob contract de arriba y el grafo de 3 ramas.
3. `SamanTools/registro.py._inyectar_frame_manager()` agrega `~/.nuke/SamanTools` a `sys.path` para que resuelvan tanto `__import__('frame_manager')` como `import breakdown_datos`.
4. `install.sh` copia `SamanTools/` completo a `~/.nuke/SamanTools/`: los dos módulos viajan juntos, no hay deploy separado.
5. Register so the node appears in the TAB/Nodes search: `registro.py.instalar()` adds a fixed "Breakdown (frames por tabla)" command under "Insertar Nodo" (menu superior SamanTools) and the TAB submenu "HTLR · Saman · Samán", inserting the global `nodos/Breakdown.gizmo` via `nuke.nodePaste`. No project scan required.
6. Verify in Nuke: crear el nodo, editar filas, Generar, y confirmar ramas/ContactSheet/expresiones. Verificación sin GUI:
   ```bash
   NUKE_PATH=<repo>/SamanTools/nodos /Applications/Nuke17.1v3/Nuke17.1v3.app/Contents/MacOS/Nuke17.1 -t <script>
   ```
   El script debe hacer `sys.path.insert(0, "<repo>/SamanTools")`, `nuke.pluginAddPath(...)`, `nuke.createNode("Breakdown")`, y luego `frame_manager.sincronizar_grafo(nodo)` dentro de `with nuke.Undo():` (no necesita `QApplication`).

## Caveats / Gotchas

- If the table "disappears", the knob `table_ui` expression is failing — almost always the `makeUI` contract (container class, not the widget directly), or the module was loaded before the fix (stale `import`); re-import with `importlib.reload(frame_manager)` and re-create the node (open knob instances do NOT re-evaluate).
- Los dos módulos viajan juntos a `~/.nuke/SamanTools/`. Si `breakdown_datos.py` no está, `frame_manager` falla al importarse y el panel no aparece.
- PyCustom knob type 52 evaluates `__import__('frame_manager').FrameManagerKnob()` alive — do not depend on `__main__`.
- Nuke keyword `tags=` is NOT supported in `Menu.addCommand` on this version — never use it.
- Tests de la lógica de datos: `python -m pytest tests/test_breakdown_datos.py tests/test_breakdown_knobs.py tests/test_breakdown_columnas.py` (no requieren Nuke ni Qt).
- Ojo con los tests de `.gizmo` basados en regex: todas las líneas van indentadas con un espacio, así que `^nombre\s+` nunca matchea y el test pasa por la razón equivocada. Usá `^\s*nombre\s+` (pasó de verdad con un test que decía verificar los defaults).
- `tests/test_breakdown_knobs.py` tiene un test que compara el pool declarado en el `.gizmo` con `POOL`: si agregás o quitás filas, actualizá los dos lados o la suite falla.
- Verificación headless ejecutada y esperada en Nuke 17.1v3: crear nodo, migrar comps viejos (vacío, 3 filas, 40 filas), generar con 2/6/32 filas, `resMult` preservado, un `Merge1` del comp del artista intacto y round-trip save/load sin re-migrar.

## Output Contract

Return: the `.gizmo` path, the `breakdown_datos.py` + `frame_manager.py` paths, confirmation the PyCustom knob uses `FrameManagerKnob` (class with `makeUI`), the knob contract present (`N`, `F_<i>`, `L_<i>`, `datos_ver`, `frame_data` legacy, `table_ui`, `Desfase`, `VerTexto`, buttons), and the verification done (pytest + headless Nuke: migración vacía/3/40 filas, round-trip, `resMult`).

## References

- `SamanTools/nodos/Breakdown.gizmo` — the global reference group this skill generalizes.
- `SamanTools/frame_manager.py` — widget Qt + generación del grafo.
- `SamanTools/breakdown_datos.py` — storage tipado, máscara de capas, reconciliación y migración legacy.
- `tests/test_breakdown_datos.py` — la especificación ejecutable de la lógica de datos.
- `tests/test_breakdown_columnas.py` — modelo de columnas, valores por tipo y las cuatro ramas de migración a `datos_ver = 2`.
- `tests/test_breakdown_knobs.py` — contrato de knobs: pool vs gizmo, defaults ausentes, escritura por fila, limpieza acotada, migración con respaldo.
- `/Volumes/wupm/2026/HTLR/.opencode/skills/nuke-gallery-gizmo/SKILL.md` — sibling skill; same project-level skill conventions.
- `/Users/emanuel/.nuke/SamanTools/` — bootstrap (registro.py `_inyectar_frame_manager`) and TAB registration (proyecto.py).
