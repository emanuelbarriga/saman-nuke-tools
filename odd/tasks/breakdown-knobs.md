# Feature: Breakdown con knobs nativos y generación incremental

Nodo global `Breakdown` (SamanTools): storage tipado, generación incremental del grafo interno y migración del JSON legacy.
Alcance decidido: opción A (eficiencia + knobs nativos seguros); las 5 capas quedan fijas.

## Specs

- **S1** — El pedido original: «Quiero que mejores el nodo del breakdown para que aproveche al máximo las herramientas https://learn.foundry.com/nuke/developers/63/ndkdevguide/knobs-and-handles/knobtypes.html existentes y lo hagas más eficiente».
- **S2** — Alcance elegido por el humano: «A · Eficiencia + knobs nativos seguros»: storage tipado (Int/Enum/Bool), generar incremental, fix de `resMult`, migración automática del JSON legacy, sin knobs nuevos visibles al artista.
- **S3** — Las 5 capas visuales quedan fijas: «Fijas (recomendado)» → `brillo, muzzle, humo, impacto, sangre` con bits 1, 2, 4, 8, 16.
- **S4** — Storage tipado: knobs `nuke.Int_Knob` por fila (`F_<i>` frame, `L_<i>` máscara de capas) más `N` con la cantidad de filas. Pool fijo de 32 filas; el pool se declara `+INVISIBLE` en el `.gizmo`.
- **S5** — Sin JSON en el camino caliente: editar una celda escribe como máximo los 2 knobs de esa fila, no re-serializa todas las filas.
- **S6** — `generar()` incremental: reusa los `FrameHold_Auto_<i>`/`Text_Auto_<i>` existentes, crea solo los faltantes, borra solo los sobrantes y escribe cada knob solo si el valor difiere. Nunca toca nodos de otro grupo.
- **S7** — `resMult` del `ContactSheetAuto` se crea si falta y **no** se reescribe: el valor elegido por el artista sobrevive a cada Generar.
- **S8** — Migración automática: si `frame_data` (string legacy) contiene JSON no vacío, se vuelca al storage tipado una sola vez y el knob legacy queda vacío. Si no parsea, se ignora sin romper y la tabla arranca vacía.
- **S9** — Compatibilidad de API: los botones del grupo siguen resolviendo la instancia viva del widget; el knob PyCustom (52) sigue apuntando a `__import__('frame_manager').FrameManagerKnob()`.
- **S10** — La lógica de datos vive en un módulo sin Qt (`breakdown_datos.py`) para poder probarse con pytest fuera de Nuke.

## Tasks

| ID | Specs | Ruta | Commit |
| --- | --- | --- | --- |
| T1 | S3, S4, S5, S8, S10 | Tests de `breakdown_datos` + contrato de knobs (`test_breakdown_datos.py`, `test_breakdown_knobs.py`) | `23f874f` |
| T2 | S4, S5, S8, S10 | `SamanTools/breakdown_datos.py`: lógica pura + I/O de knobs tipados + migración versionada | `23f874f` |
| T3 | S5, S6, S7 | `SamanTools/frame_manager.py`: widget PySide, escritura por celda, `generar()` incremental | `61efe82` |
| T4 | S4, S9 | `SamanTools/nodos/Breakdown.gizmo`: contrato de knobs nuevo | `61efe82` |
| T5 | S1, S10 | Sincronizar assets del skill + documentar el contrato en `SKILL.md` | `docs` |
| T6 | S6, S7, S8 | Verificación headless en Nuke 17.1v3: crear nodo, generar, round-trip save/load | verificado, sin archivo |

## Delivery

Rama `feat/breakdown-knobs-nativos`, tres commits por concern:

1. `23f874f` — `breakdown_datos.py` + sus dos suites (857 líneas): el módulo de datos y sus tests son **una sola unidad**. Los tests son la especificación ejecutable del módulo; separarlos dejaría un commit con código sin contrato o con tests que importan código inexistente. Es la única slice que supera ~400 líneas y es deliberado.
2. `frame_manager.py` + `Breakdown.gizmo` — el comportamiento del nodo (widget, generación incremental, contrato de knobs). No se puede entregar antes que (1): importa `breakdown_datos`.
3. Assets del skill + `SKILL.md` + este documento — documentación y espejo.

Ninguna parte es entregable por separado: el gizmo necesita los módulos y los tests necesitan el contrato. Se revisan los tres juntos.

## Log

- **L1** — «Quiero que mejores el nodo del breakdown para que aproveche al máximo las herramientas https://learn.foundry.com/nuke/developers/63/ndkdevguide/knobs-and-handles/knobtypes.html existentes y lo hagas más eficiente»
- **L2** — Decisión del humano, alcance: «A · Eficiencia + knobs nativos seguros». Preview aceptado: storage `F_1` Int + `L_1` Int en grupo colapsado, generar incremental, `resMult` preservado, updates O(1) por celda, undo coalescido, `frame_data` legacy migrado una vez.
- **L3** — Decisión del humano, capas: «Fijas (recomendado)» → `KEYS = [brillo, muzzle, humo, impacto, sangre]`, máscara de 5 bits.
- **L4** — Evidencia de exploración (Nuke 17.1v3, ejecución real con `Nuke -t`):
  - `nuke.Table_Knob` no existe en la API Python → no hay tabla nativa; el knob PyCustom 52 sigue siendo la única vía de UI.
  - `Bitmask_Knob` no sobrevive el guardado: serializa como `addUserKnob {4 ... M {...}}` y al recargar vuelve como `Enumeration_Knob`. Descartado como storage.
  - Verificados con round-trip save/load en un `.gizmo`: `Int_Knob` (`{3}`), `Enumeration_Knob` (`{4 ... M {...}}`), `Boolean_Knob` (`{6}`), `File_Knob` (`{2}`), `BBox_Knob` (`{15}`), `Text_Knob` (`{26}`), `Tab_Knob` (`{20}`).
  - `nuke.Array_Knob` crea un array de floats cuyo tamaño no se puede cambiar tras crearlo (`resize()` no surte efecto y sólo serializa el primer valor) → descartado para almacenar N frames.
  - Los knobs `+INVISIBLE` de un gizmo persisten su valor entre save/load (verificado: `F_1 42` vuelve como 42).
- **L5** — Hallazgos del código previo que la feature corrige: `_configurar_contactsheet` forzaba `resMult = 1.0` en cada Generar; `guardar_datos()` re-serializaba todo el JSON por cada tecla; `actualizar_frames_en_vivo` reescribía todas las expresiones por cada edición; `generar()` borraba y recreaba todo el grafo interno.
- **L6** — El asset del skill (`skills/nuke-breakdown-gizmo/assets/frame_manager.py`) estaba desactualizado respecto de `SamanTools/frame_manager.py` (le faltaba el acotado del borrado por `pparent()`). T5 sincroniza ambos.
- **L7** — Verificación independiente (Risk: item 1, migración de datos persistidos) encontró dos regresiones reales de la migración y ambas se corrigieron antes de cerrar:
  1. Con más de `POOL` filas legacy, la migración truncaba a 32 **y** blanqueaba `frame_data`: pérdida irreversible. Corregido con el marcador `datos_ver` (`KNOB_VERSION`, `VERSION_DATOS`) y `legacy_excedente()`: se migran las que entran, el JSON original se conserva como respaldo y el widget avisa con `nuke.message`.
  2. Un comp donde el artista vació la tabla (`frame_data "[]"`, sin knobs tipados) revivía las 3 filas de ejemplo por los defaults del `.gizmo`. Corregido: `N`/`F_<i>`/`L_<i>` shipean en cero y `frame_data` conserva el JSON de ejemplo de 3 filas como default legacy, así nodo nuevo y comp viejo recorren el mismo camino de migración y un comp vaciado queda vacío.
- **L8** — Corregido además un bug latente del código previo: `nuke.Node` **no** tiene `pparent()` en Nuke 17.1, así que el `try/except Exception: continue` de la limpieza acotada se tragaba la excepción y no borraba nunca nada. Ahora `_padre()` prueba `parent()` (API vigente) y `pparent()`, sin tragarse errores.
- **L9** — Advertencias del verificador atendidas: bucle de limpieza de `escribir_filas` acotado con `min(N, POOL)`; `filas_desde_legacy` ya no trunca al pool (decide la migración). Cambio de comportamiento documentado: un frame escrito como `"12.6"` ahora redondea a 13 (antes `int()` truncaba a 0 por la excepción de parseo).
- **L10** — Evidencia de verificación final: `pytest tests/` → 678 passed. Headless en Nuke 17.1v3 → 25/25 checks (nodo nuevo migra a 3 filas, comp vaciado queda en 0, comp de 40 filas migra 32 y conserva el respaldo, `Merge1` del comp del artista sobrevive, `resMult` en 0.5 se preserva, grillas 1x1/2x1/3x2/6x6, ramas 1..32 con su `firstFrame`) y 11/11 en round-trip save/load (nadie re-migra, `datos_ver` en 1, `legacy_excedente` sigue en 8).

## Specs v2 — columnas configurables

- **S11** — Pedido del humano, verbatim: «Quisiera que en una segunda ventana se pudiera establecer la cantidad y tipos de columnas. Por ejemplo Si el usuario solo quiere 2 columanas, con nombres personalizados. Él podrá definirlo. Me hago entender?»
- **S12** — Decisiones del humano: «Segunda pestaña en el mismo nodo»; «Tildar, texto y número»; un nodo nuevo arranca con «2 columnas de ejemplo».
- **S13** — La pestaña `Columnas` declara knobs nativos: `Cantidad` (Int, 0–8) y, por cada slot 1..8, `Col_<i>_nombre` (String) y `Col_<i>_tipo` (Enumeration `{Tilde Texto Numero}`). El botón `Aplicar columnas` reconstruye la tabla; toda acción de la tabla también relee la configuración.
- **S14** — La columna `Frame` es fija, siempre la primera, con el comportamiento actual.
- **S15** — Storage sin crecer en el camino caliente: los tildes siguen en `L_<i>` (bit = slot de columna − 1, hasta 8); texto y número van a un único knob `TXT` con `{fila: {slot: valor}}`, escrito sólo al confirmar una celda (demorado) y sólo si el valor cambió.
- **S16** — Cambiar el tipo de una columna no borra datos: los valores quedan ocultos en su storage y reaparecen si se vuelve al tipo anterior.
- **S17** — Migración a `datos_ver = 2`: comps del gizmo original (`datos_ver` ausente y `frame_data` no vacío) y comps de la v1 (`datos_ver = 1`) pasan a las 5 columnas canónicas, con las máscaras intactas. Un nodo nuevo (`datos_ver` 0 y `frame_data` vacío) conserva las 2 columnas de ejemplo y no migra filas. Un comp viejo con la tabla vacía (`frame_data "[]"`) queda en 0 filas (sin filas fantasma).
- **S18** — Celda numérica: al confirmar, se normaliza si parsea; si no parsea, la celda vuelve al valor guardado (no se escribe basura ni se pierde el valor anterior).

## Tasks v2

| ID | Specs | Ruta | Commit |
| --- | --- | --- | --- |
| T7 | S13, S15, S16, S17, S18 | Modelo de columnas + textos + migración v2 en `breakdown_datos.py`, con tests |
| T8 | S13, S15, S16, S18 | Tabla dinámica por tipo, debounce y `aplicar_columnas` en `frame_manager.py` |
| T9 | S13, S14 | Pestaña `Columnas` + knob `TXT` + defaults de ejemplo en `Breakdown.gizmo` |
| T10 | S11, S12 | Assets del skill + `SKILL.md` |
| T11 | S17 | Verificación headless Nuke: las 4 ramas de migración + columnas + generación |

## Log v2

- **L11** — Las capas nunca alimentaron el grafo (sólo anotación): la feature no toca la generación de FrameHold/Text/ContactSheet.
- **L12** — Se descarta convertir valores al cambiar el tipo (S16): ocultar-y-reaparecer es reversible y no puede perder datos, a diferencia de una conversión `tilde→texto` que inventaría contenido.
- **L13** — Bug encontrado en la verificación headless de v2: `TXT` quedó declarado como `addUserKnob {3}` (Int) y `setValue` con texto explotaba con `expecting a float, str found`. Corregido a `{1}` (String) y pineado con test, junto con la nota de que declarar mal el tipo es silencioso hasta que se escribe.
- **L14** — Test vacuo encontrado y corregido: `test_el_gizmo_declara_marcador_de_version_y_no_asigna_defaults_tipados` usaba `^nombre\s+` contra un archivo donde todas las líneas van indentadas con un espacio, así que nunca matcheaba y pasaba siempre. Reescrito con `^\s*` y con la regla real de v2 (`datos_ver` sin default; los defaults de fila sí son válidos porque la migración normaliza los comps vaciados).
- **L15** — Evidencia de v2: `pytest tests/` → 715 passed. Headless Nuke 17.1v3 → 20/20 (nodo nuevo con 2 columnas de ejemplo, celdas por tipo, 3 columnas configuradas, las 4 ramas de migración, generación intacta) y 8/8 en round-trip save/load (columnas, `TXT`, `datos_ver 2`, sin re-migrar).
