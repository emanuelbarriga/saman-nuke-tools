# Feature: v3.0.0 — release con los cinco nodos rehechos

Release 3.0.0 del plugin: publica exactamente los cinco nodos rehechos por el humano y recupera del
plugin original la política de **un solo nodo de rutas por proyecto**, con fusión de duplicados.
Solo entran los cinco nodos; todo lo demás queda fuera de la superficie de instalación, no por olvido.

## Specs

- **S1** — El pedido original, textual: «Quiero sacara una versión nueva de este proyecto. Solo con 5 nodos que rehice. /Users/servermac/Documents/Nodos\ Saman/Nodos\ Estables Que podemos recuperar del plugin original? Como lo vuelvo una herramienta de rutas. Hay algo que me gusta del plguin que buscad nodos re dutas antiguos y solo deja uno que actualiza. Debe hacer solo un nodo de rutas por proyecto».
- **S2** — «Solo con 5 nodos que rehice»: la superficie instalada son cinco nodos, provenientes de `/Users/servermac/Documents/Nodos Saman/Nodos Estables` (`Breakdown_v2.gizmo`, `ColorSpaces.gizmo`, `Review_v2.gizmo`, `RutasV2_v2.gizmo`, `fSpy_v2.gizmo`), instalados como `SamanTools/nodos/{Breakdown,ColorSpaces,Review,Rutas,fSpy}.gizmo`. `Rutas.nk` deja de existir: los cinco gizmos son autocontenidos.
- **S3** — «Debe hacer solo un nodo de rutas por proyecto»: al abrir cualquier comp, la herramienta garantiza que quede un único nodo de rutas.
- **S4** — «buscad nodos re dutas antiguos y solo deja uno que actualiza»: lo que se recupera del plugin original es la detección por knobs (nunca por nombre), el marcador de versión del nodo y la migración que conserva knobs y posición: `es_nodo_rutas`, `encontrar_nodos_rutas`, `es_version_actual`, `_reconstruir_nodo` (`SamanTools/rutas.py:603,629,638,701`).
- **S5** — Decisión del humano, textual de la opción elegida: «v3.0.0: solo los 5 nodos». Panel de comentarios, render distribuido y diagnóstico de red quedan fuera de la superficie instalada.
- **S6** — Decisión del humano, textual de la opción elegida: «Bootstrap mínimo en menu.py». Los cinco gizmos quedan autocontenidos; un módulo chico, `SamanTools/rutas_unico.py`, instalado en `~/.nuke` junto al paquete, registra el hook `nuke.addOnScriptLoad` y aplica la política.
- **S7** — Decisión del humano, textual de la opción elegida: «Fusionar y dejar uno». Con dos o más nodos de rutas en un comp, el superviviente absorbe el estado de los demás y los sobrantes se borran; la fusión escribe el estado fusionado **antes** de borrar.
- **S8** — Superviviente, definido: el nodo de versión actual con más contenido (`folders` + `users`); desempate por orden de `nuke.allNodes()`. Un nodo de versión vieja nunca gana sobre uno actual. `active_user` del superviviente se conserva si sigue siendo válido tras la fusión.
- **S9** — Fusión, definida: unión de `folders` por ruta, unión de `users` por nombre, sin perder claves desconocidas del superviviente (el esquema se copia tal cual, no se reconstruye). Un nodo viejo de knobs clásicos aporta sus rutas y usuario, no se descarta.
- **S10** — Borrar es destructivo y ocurre al abrir un comp: la fusión pide confirmación una vez (`nuke.ask`); si el humano dice no, solo avisa —el comportamiento que ya existía en `avisar_duplicados` (`rutas.py:833`)— y no borra nada. En modo headless (`-t` / render) no se borra nunca: solo se avisa.
- **S11** — La política no inserta nodos: con cero nodos de rutas el hook no hace nada e informa `nada`. Insertar un nodo sigue siendo una acción explícita del menú, igual que en 2.0.0 (`crear_o_reutilizar`, `rutas.py:777`).
- **S12** — Retirar de la superficie no es borrar código: los módulos fuera de alcance siguen en el repositorio y en el historial; lo que se retira es su entrada en `SamanTools/componentes.py`, en el menú y en el `dist`. Ningún archivo fuente se elimina en esta entrega.
- **S13** — La versión es `3.0.0`, fuente única `SamanTools/__init__.py:9`, según `VERSIONING.md`.
- **S15** — Pedido del humano, textual: «si hay un nodo de rutas creado, se puede que en vez de ir donde está el nodo, el nodo se mueva a la mitad de donde está viendo el usuario en el node graph», corregido después: «el nodos de rutas se debe mover es en la posición donde está el mouse, como funciona cunado se crea un nuevo nodo». Con un nodo de versión actual, la herramienta lo pone donde nace un nodo nuevo, bajo el cursor, y **no** panea ni hace zoom. Nuke no expone el cursor del DAG: se crea un `NoOp` descartable, se lee su `xpos/ypos` y se borra, todo en el mismo paso de undo. Si el cursor no se puede leer cae al centro visible (`nuke.center()`); si tampoco, conserva la posición. En headless no mueve nada.
- **S14** — Todo comportamiento nuevo llega con test que corre sin Nuke instalado, siguiendo el stub de `tests/conftest.py`; la suite completa queda en verde y `build_dist` valida declaraciones.

## Tasks

| ID | Specs | Qué | Ruta | Commit |
| --- | --- | --- | --- | --- |
| T1 | S3-S11 | Módulo de política de nodo único: detección, versión, fusión, hook de carga. Con tests. | `SamanTools/rutas_unico.py`, `tests/test_rutas_unico.py` | `94c275a` |
| T2 | S2 | Instalar los cinco gizmos rehechos como los cinco nodos del release. | `SamanTools/nodos/` | release |
| T3 | S5, S6, S12 | Retirar de la superficie los componentes fuera de alcance y declarar los cinco nodos. | `SamanTools/componentes.py` | release |
| T4 | S6 | Registrar el hook de política en el bootstrap. | `SamanTools/registro.py`, `tests/test_menu.py` | release |
| T5 | S13, S14 | Versión 3.0.0 y documentación al estado real. | `SamanTools/__init__.py`, `README.md`, `docs/ARQUITECTURA.md` | release |
| T6 | S14 | Suite completa y `build_dist` en verde; riesgo y review nativo. | — | verificado |

## Log

- **L1** — Pedido original del humano, textual: «Quiero sacara una versión nueva de este proyecto. Solo con 5 nodos que rehice. /Users/servermac/Documents/Nodos\ Saman/Nodos\ Estables Que podemos recuperar del plugin original? Como lo vuelvo una herramienta de rutas. Hay algo que me gusta del plguin que buscad nodos re dutas antiguos y solo deja uno que actualiza. Debe hacer solo un nodo de rutas por proyecto».
- **L2** — Evidencia de exploración: los cinco gizmos son autocontenidos (`Cerebro_Python`, sin `import SamanTools`); `RutasV2_v2.gizmo` embebe su motor pero **no** trae la política de nodo único (sin `es_nodo_rutas`, sin migración; sus `nuke.delete` son de backdrops y `del_folder`). El comportamiento a recuperar vive en `SamanTools/rutas.py:603-857`.
- **L3** — Evidencia: un `.gizmo` no puede garantizar la política porque con cero nodos en el comp no corre nada, y el `addOnScriptLoad` que registra el propio motor solo existe en la sesión donde el nodo se cargó. Por eso la política necesita el bootstrap (`registro._registrar_hooks_de_carga`, `registro.py:308`).
- **L4** — Decisión del humano: alcance «v3.0.0: solo los 5 nodos».
- **L5** — Decisión del humano: soporte «Bootstrap mínimo en menu.py».
- **L6** — Decisión del humano: duplicados «Fusionar y dejar uno».
- **L7** — Evidencia: `ColorSpaces` es el único nodo realmente nuevo; los otros cuatro ya existían como asset en `SamanTools/nodos/`. `rutas_global.py` queda fuera: era un shim cuyo retiro estaba planificado y nunca se ejecutó (`odd/tasks/rutas-nodo.md:27-29`).
- **L8** — Evidencia de la instalación (T2): los cinco gizmos rehechos habían perdido arreglos del 2.0.0 que la suite pinneaba. Se re-aplicaron: `Breakdown.gizmo` ya no serializa `datos_ver 2` (S17: un comp arrancaba creyéndose migrado), y `Review.gizmo` ya no arrastra `render_settings_schema` ni `monitorOutNDISenderName` del Viewer. La grilla de columnas y los nombres fijos del Breakdown se conservan con otra forma (`N` + `F_i`/`L_i` + `COLUMNAS_CANONICAS`, mismos `_NODOS_BASE`), así que se actualizó el test a ese contrato en vez de darlo por perdido.
- **L9** — Evidencia de la entrega: suite completa `836 passed` (`python3.14` + PySide6 6.12) y `python3 -m SamanTools.build_dist` → `dist/samantools` con 10 módulos. El gate del build encontró una dependencia real que había que cortar: `proyecto.py` importaba el módulo v1 `rutas.py`; ahora lee el proyecto y sincroniza el entorno por `rutas_unico`.
- **L10** — Fuera de alcance, sin tocar: `skills/saman-render-launcher/` y la captura de pantalla sin seguimiento quedaron sin versionar; no integran este release.
- **L11** — Review nativo: el slice completo frenó con `lens_context_budget_exceeded` (3356 líneas × 4 lentes). Partido según lo que pide el provider: el commit de release (`db4e69e`) evaluó `reviewDue: false` (riesgo medio, `under_budget`, sin autoridad creada); el commit de la política (`94c275a`), aislado en un worktree y con dos lentes, quedó con el consentimiento del host **rechazado para ese candidato** (`lineage_created: false`, `mutation_performed: false`, nada que abandonar ni reparar). El mismo candidato no se reintentó.
- **L12** — Verificador independiente: **no se lanzó**, por la restricción del humano de usar solo modelos de opencode go. Queda declarado como no disponible, nunca como aprobado. La verificación que sí se ejecutó es la del slice completo (836 tests, `py_compile`, `build_dist`) más la lectura directa del orden escritura→borrado en `_actualizar_nodo_viejo` y en el hook de fusión: si el estado no se escribe, no se borra nada.
- **L15** — Corrección de S15: el destino no es el centro de la vista sino el cursor. `_posicion_del_cursor` usa el workaround estándar (nodo descartable) porque Nuke no expone el cursor del DAG; `_centro_de_la_vista` queda como respaldo y `_enfocar` ya no interviene en la rama `unico`. El único borrado observable de ese camino es el descartable.
- **L14** — S15 (nodo al centro de la vista): `_mostrar_en_la_vista` reemplaza a `_enfocar` en la rama de un nodo actual. `_enfocar` (que panea con `zoomToFitSelected`) se conserva para las ramas de creación y fusión. Caveat conocido: `nuke.center()` devuelve el centro del grupo que se está viendo; si el artista está dentro de un Group cuando dispara la acción, el nodo de rutas queda en esas coordenadas.
- **L13** — Slices: 2365 líneas en `94c275a` y 991 en `db4e69e`, muy por encima de las ~400 de un slice cómodo. El límite de review del provider ya lo confirmó; la forma de publicación (PR encadenado) queda como decisión del humano.
