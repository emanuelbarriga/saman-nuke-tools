# Feature: dist verificada (carpeta con lo que funciona al 100%)

Generación de `dist/samantools/` desde la fuente única, con manifiesto de componentes y verificación ejecutable.
Solo entran los componentes listados por el humano; todo lo demás queda afuera por dependencia, no por olvido.

## Specs

- **S1** — El pedido original, textual: «Crea una nueva carpeta con todo lo que funcione al 100%. Me refiero a Fspy, cambio de espacio de color, nodo de rutas, breakdown, acerca de saman tools, y actualización, y los nodos por proyecto. Debes verificaar que todo lo que migres funcione al 100%».
- **S2** — Los componentes que entran son exactamente siete: `fspy`, `colorspace`, `rutas`, `breakdown`, `acerca_de`, `actualizacion`, `nodos_proyecto`. Nada más entra sin pedido explícito.
- **S3** — Decisión del humano sobre la forma, textual de la opción elegida: «Generada: dist/samantools/ desde una sola fuente». La carpeta es un artefacto generado, nunca editado a mano; se regenera en un comando.
- **S4** — Decisión del humano: «Incluir fSpy y Breakdown WIP, verificando todo». Entra fSpy completo (`fspy.py`, `fspy_core.py`, `nodos/fSpy.gizmo`, `tests/test_fspy_core.py`) y el estado actual de Breakdown, sea cual sea.
- **S5** — Decisión del humano: verificación con «Venv con python3.13 + PySide6». El entorno ya existe en `/tmp/saman-full` (PySide6 6.12.0, pytest 9.2.0) y es el que define si un componente pasa o no.
- **S6** — Criterio de "funciona al 100%": (a) la suite completa pasa en `/tmp/saman-full` sin fallos; (b) todo `.py` del dist pasa `py_compile`; (c) todo módulo incluido importa sin excepciones; (d) no hay import, entrada de menú ni ruta de archivo que apunte a un módulo o asset AUERA del dist; (e) los tests de cada componente están listados en el manifiesto con su resultado.
- **S7** — El manifiesto (`dist/samantools/MANIFIESTO.md`) declara por componente: id, etiqueta, módulos incluidos, nodos/assets, tests asociados, cantidad de tests y estado (`verificado` / `excluido` con motivo), más la fecha y el commit de origen.
- **S8** — El build calcula el cierre de dependencias real (imports transitivos dentro de `SamanTools`), no una lista escrita a mano: si un componente necesita `limpiar`, `entorno` o `nombres`, entran aunque no sean componentes.
- **S9** — El build falla fuerte, con mensaje accionable, si: falta un archivo declarado, un import del dist apunta afuera del dist, o un componente activo necesita un módulo excluido.
- **S10** — Fuera del dist, por decisión: `panel_comentarios.py`, `vfxflow_auth.py`, `vfxflow_config.py`, `vfxflow_datos.py`, `sesion_vfxflow.py`, `diagnostico_red.py` y todo `render_distribuido/`. Si alguno resulta ser dependencia de un componente activo, el build lo informa en vez de incluirlo en silencio.
- **S11** — Lo que no está verificado se declara no verificado. Ningún componente entra al dist con estado `verificado` sin evidencia ejecutada en esta sesión.
- **S12** — «Actualización» se entrega con `bootstrap/menu.py` dentro del dist (es el `.nuke/menu.py` del artista: auto-update por `git pull --ff-only`, alerta y botones) y con un test que fija su contrato de seguridad: compila, define sus puntos de entrada, usa `--ff-only` y **nunca** `reset --hard` (regla de `docs/ARQUITECTURA.md` §4). Estado `verificado` solo con ese test en verde.
- **S13** — «fSpy» lleva icono propio: asset `SamanTools/fSpy.svg` (32×32, misma familia visual que `SamanTools/ChangeColorSpace.svg`: cuerpo `#1C1C1C`, acento en gradiente, highlight claro), referenciado con `icon=_ruta_icono("fSpy.svg")` en los DOS `addCommand` de fSpy (menú SamanTools y menú Nodes) y declarado en `componentes.py` para que viaje al dist. Sin `icon=`, Nuke muestra el nombre del comando como texto en la barra: ese es el defecto reportado.

## Tasks

| ID | Specs | Ruta | Commit |
| --- | --- | --- | --- |
| T1 | S2, S7, S8 | `SamanTools/componentes.py`: manifiesto único (id, etiqueta, módulos, assets, tests) | pendiente |
| T2 | S6, S9 | `SamanTools/build_dist.py`: cierre de dependencias por AST, copia a `dist/`, `MANIFIESTO.md`, fallos accionables | pendiente |
| T3 | S6, S10 | Compuertas en `registro.py`: ninguna entrada de menú ni import apunta a un módulo fuera del dist | pendiente |
| T4 | S6, S11 | Tests del build y del manifiesto (`tests/test_componentes.py`, `tests/test_build_dist.py`) | pendiente |
| T5 | S5, S6 | Generar `dist/samantools/` y correr la suite completa en `/tmp/saman-full` | pendiente |
| T6 | S6, S7 | Smoke test del dist: importar cada módulo incluido y verificar que los assets declarados existen | pendiente |
| T7 | S7, S11 | `MANIFIESTO.md` final con el veredicto por componente | pendiente |
| T8 | S11, S12 | Corregir `actualizacion`: `bootstrap/menu.py` al dist + `tests/test_bootstrap_menu.py` con el contrato `--ff-only`; jamás `verificado` con 0 tests | pendiente |
| T9 | S13 | Icono de fSpy: asset `SamanTools/fSpy.svg`, `icon=` en los dos `addCommand`, declaración en `componentes.py`, test de que toda referencia `_ruta_icono(...)` resuelve y de que `_insertar_fspy` no lanza, y regeneración del dist | pendiente |

## Log

- **L1** — «Crea una nueva carpeta con todo lo que funcione al 100%. Me refiero a Fspy, cambio de espacio de color, nodo de rutas, breakdown, acerca de saman tools, y actualización, y los nodos por proyecto. Debes verificaar que todo lo que migres funcione al 100%».
- **L2** — Decisiones del humano: carpeta generada desde una sola fuente; incluir fSpy y Breakdown verificándolos; verificación con venv python3.13 + PySide6.
- **L3 (evidencia)** — Auditoría de estado: `fspy.py`, `fspy_core.py`, `nodos/fSpy.gizmo` y `tests/test_fspy_core.py` estaban SIN COMMITEAR al iniciar. Breakdown quedó commiteado entre sesiones (`c12d358`, `c112735`, `6d47ea7`). El árbol se movió bajo esta sesión y se reconcilió antes de construir.
- **L4 (evidencia)** — Otro commit apareció entre sesiones: `0c6ccb7 fix(rutas): define PYTHON_* al cargar el script desde el repo`, que agrega `rutas.aplicar_variables_desde_nodo()` + `registro._registrar_hooks_de_carga()` con `nuke.addOnScriptLoad` y 9 tests. Eso resuelve la incógnita T4 de `rutas-nodo.md` (si `knobChanged` corre al abrir un comp: no es confiable, por eso el hook) y vuelve innecesario el shim de `rutas_global.py`.
- **L5 (evidencia)** — Línea base de verificación en el venv con PySide: 730 tests PASS, 0 FAIL, tras corregir `tests/test_menu.py`, que afirmaba la existencia del panel de rutas retirado en `489f2e7`. El fallo era invisible sin PySide: demuestra por qué el criterio S5 es el correcto.
- **L7 (pedido del humano)** — «Necesito un logo para fspy, porque en el menu toolbar aparece un texto larguisimo que no funciona». Causa: los dos `addCommand` de fSpy se registran sin `icon=`, a diferencia de ChangeColorSpace, así que Nuke dibuja el nombre del comando como texto. Primer diseño del SVG incluía un punto de fuga con dos trazos: renderizado a 256 px se leía como una llave inglesa, así que se descartó y quedó cámara + lente calibrada, verificado visualmente con `qlmanage`.
- **L6 (hallazgo de verificación del padre)** — La primera generación del dist declaró `actualizacion — Estado: verificado` con `Tests asociados:` vacío y `Cantidad de tests: 0`, y `bootstrap/menu.py` no fue incluido en `dist/samantools/`. Es una violación directa de S11 y de S6e: el componente que el humano pidió explícitamente quedaba fuera del artefacto y su estado era falso. Se agrega S12 y T8 para corregirlo con un test real del contrato de actualización. El resto de la verificación del padre sí pasó: el trabajo fSpy sin commitear quedó preservado en `registro.py` (6 líneas fSpy + `_insertar_fspy`), y los otros 6 componentes están en el dist con sus tests asociados.
