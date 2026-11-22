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
- **S14** — Todo comportamiento nuevo llega con test que corre sin Nuke instalado, siguiendo el stub de `tests/conftest.py`; la suite completa queda en verde y `build_dist` valida declaraciones.

## Tasks

| ID | Specs | Qué | Ruta | Commit |
| --- | --- | --- | --- | --- |
| T1 | S3-S11 | Módulo de política de nodo único: detección, versión, fusión, hook de carga. Con tests. | `SamanTools/rutas_unico.py`, `tests/test_rutas_unico.py` | C1 |
| T2 | S2 | Instalar los cinco gizmos rehechos como los cinco nodos del release. | `SamanTools/nodos/` | C2 |
| T3 | S5, S6, S12 | Retirar de la superficie los componentes fuera de alcance y declarar los cinco nodos. | `SamanTools/componentes.py` | C2 |
| T4 | S6 | Registrar el hook de política en el bootstrap. | `SamanTools/registro.py`, `tests/test_menu.py` | C2 |
| T5 | S13, S14 | Versión 3.0.0 y documentación al estado real. | `SamanTools/__init__.py`, `README.md`, `docs/ARQUITECTURA.md` | C2 |
| T6 | S14 | Suite completa y `build_dist` en verde; riesgo y review nativo. | — | — |

## Log

- **L1** — Pedido original del humano, textual: «Quiero sacara una versión nueva de este proyecto. Solo con 5 nodos que rehice. /Users/servermac/Documents/Nodos\ Saman/Nodos\ Estables Que podemos recuperar del plugin original? Como lo vuelvo una herramienta de rutas. Hay algo que me gusta del plguin que buscad nodos re dutas antiguos y solo deja uno que actualiza. Debe hacer solo un nodo de rutas por proyecto».
- **L2** — Evidencia de exploración: los cinco gizmos son autocontenidos (`Cerebro_Python`, sin `import SamanTools`); `RutasV2_v2.gizmo` embebe su motor pero **no** trae la política de nodo único (sin `es_nodo_rutas`, sin migración; sus `nuke.delete` son de backdrops y `del_folder`). El comportamiento a recuperar vive en `SamanTools/rutas.py:603-857`.
- **L3** — Evidencia: un `.gizmo` no puede garantizar la política porque con cero nodos en el comp no corre nada, y el `addOnScriptLoad` que registra el propio motor solo existe en la sesión donde el nodo se cargó. Por eso la política necesita el bootstrap (`registro._registrar_hooks_de_carga`, `registro.py:308`).
- **L4** — Decisión del humano: alcance «v3.0.0: solo los 5 nodos».
- **L5** — Decisión del humano: soporte «Bootstrap mínimo en menu.py».
- **L6** — Decisión del humano: duplicados «Fusionar y dejar uno».
- **L7** — Evidencia: `ColorSpaces` es el único nodo realmente nuevo; los otros cuatro ya existían como asset en `SamanTools/nodos/`. `rutas_global.py` queda fuera: era un shim cuyo retiro estaba planificado y nunca se ejecutó (`odd/tasks/rutas-nodo.md:27-29`).
