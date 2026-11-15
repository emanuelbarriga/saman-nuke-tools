# Feature: Nodo Rutas como autoridad única

Retiro del panel global de rutas y endurecimiento del nodo `Rutas` (portabilidad, diagnóstico, mantenibilidad).
El nodo pasa a ser la única fuente de verdad de `PYTHON_TO_VFX/COMP/FROM_VFX`.

## Specs

- **S1** — El pedido original, textual: «Necesito que estudies en profundidad los nodos y el panel de rutas de este proyecto».
- **S2** — La decisión de alcance, textual: «Entonces eliminemos todo lo del panel y centrémonos en mejorar el nodo de rutas, con todos sus problemas».
- **S3** — El alcance del retiro NO incluye el panel de comentarios (`SamanTools/panel_comentarios.py`, 4267 líneas, producto VFXFlow independiente). Solo se retira el panel de rutas: `panel_rutas.py`, `rutas_global.py`, su test y los dos puntos de enganche en `registro.py`.
- **S4** — Decisión del humano sobre el shim de arranque (`registro.py`, hook `aplicar_global()`), textual: «Si borro el shim puedo ocasionar problemas con el funcionamiento actual?» — se resuelve con medición previa, no por opinión: cuántos `.nk` del proyecto tienen Reads dinámicos `[python {PYTHON...}]` y NO tienen el nodo Rutas (`UsuarioActivo`). Cero → se retira en el mismo momento. Mayor que cero → se migran esos comps (insertar el nodo) y después se retira.
- **S5** — Rama de trabajo: la actual `feat/breakdown-knobs-nativos`, con el retiro en un commit propio `chore(rutas): retirar panel global de rutas`, sin arrastrar los cambios fSpy sin commitear de `registro.py`.
- **S6** — El nodo nunca debe lanzar traceback por falta de plugin: si `from SamanTools import rutas` falla, el nodo informa el estado en sí mismo en lugar de romper el `knobChanged`.
- **S7** — El nodo es autosuficiente para resolver los Reads: setea `__main__.PYTHON_TO_VFX/COMP/FROM_VFX` desde sus propios knobs, con o sin plugin instalado. Ese fallback reemplaza funcionalmente al shim retirado.
- **S8** — Los ~10 KB de Python embebido en `Rutas.nk`/`Rutas.gizmo` (`scan_1..4`, `python_button`, `copy_*`) se mueven a un módulo importable y testeable con el stub de `nuke` de `tests/conftest.py`.
- **S9** — Inconsistencia a corregir: `scan_1` agrupa clones con `id(n['file'])` y `scan_2/3/4` con `n['file'] == grupo[0]['file']`. Un solo criterio para los cuatro botones.
- **S10** — Los fallos de recarga dejan de ser silenciosos: `_re_evaluar_y_recargar` reporta por Read (recargado / sin cambio / falló + motivo) en lugar de `except: continue`.
- **S11** — Los nombres de knob dejan de estar duplicados en seis lugares: una fuente única genera los 9 nombres, los grupos del panel de UI del nodo y la visibilidad. Un test parsea `SamanTools/nodos/Rutas.nk` y afirma que sus knobs coinciden con los generados (detector de drift código ↔ nodo).
- **S12** — `Rutas.nk` y `Rutas.gizmo` deben ser idénticos salvo el preámbulo de instrucciones del `.nk`, y eso debe estar verificado por un test, no solo escrito en `docs/ARQUITECTURA.md`.
- **S13** — Validación al aplicar rutas: vacía, inexistente, formato de otro SO, o que no termine en `TO_VFX|COMP|FROM_VFX` produce diagnóstico visible. «Cambiar Proyecto» explica por qué cambió 0 rutas (regex sin match) en vez de informar solo el número.
- **S14** — Los cambios de comportamiento del nodo llevan su test con el stub de `nuke`; ningún cambio de nodo se valida solo mirando el Script Editor de Nuke.

## Tasks

| ID | Specs | Ruta | Commit |
| --- | --- | --- | --- |
| T1 | S3, S5 | `SamanTools/panel_rutas.py` fuera; entrada de menú «Panel de Rutas» fuera de `registro.py`; `test_rutas_global.py` se conserva hasta retirar su módulo | este commit |
| T2 | S4 | Medición read-only sobre `/Volumes/wupm/2026`: comps con Reads dinámicos, con y sin nodo Rutas | en curso |
| T3 | S4, S7 | Retiro de `rutas_global.py` + hook de arranque, condicionado a T2 | pendiente |
| T4 | S6 | Verificación empírica: ¿corre `knobChanged` al cargar un comp? (el fallback de S7 depende de esto) | pendiente |
| T5 | S6, S14 | `knobChanged` defensivo con aviso en el nodo cuando falta el plugin | pendiente |
| T6 | S7, S14 | Fallback de `PYTHON_*` desde los knobs del nodo | pendiente |
| T7 | S9 | Criterio único de agrupado de clones en los cuatro botones de escaneo | pendiente |
| T8 | S10 | Reporte por Read en `_re_evaluar_y_recargar` | pendiente |
| T9 | S8, S14 | `rutas_scan.py`: escaneo, conversión y copiado fuera del `.nk`, con tests | pendiente |
| T10 | S11 | Fuente única de nombres de knob + test de drift contra `Rutas.nk` | pendiente |
| T11 | S12 | Test de paridad `Rutas.nk` ↔ `Rutas.gizmo` | pendiente |
| T12 | S13 | Validación de rutas + diagnóstico de «Cambiar Proyecto» | pendiente |
| T13 | S3 | `README.md` y `docs/ARQUITECTURA.md` sin el panel de rutas | pendiente |

## Log

- **L1** — «Necesito que estudies en profundidad los nodos y el panel de rutas de este proyecto».
- **L2** — «Qué crees que podemos optimizar, tengo el nodo de Rutas funcional y tengo el panel parcialmente funcional. Qué críticas le harías y como las mejorarías?».
- **L3** — «Quisiera saber qué es mejor, si el nodo pueda funcionar sin el plugin instalado o que se deba instalar el plugin para que funcione? Que gano en tener el nodo como actualmente lo tengo?».
- **L4** — «Entonces eliminemos todo lo del panel y centrémonos en mejorar el nodo de rutas, con todos sus problemas. De acuerdo?».
- **L5** — «Si borro el shim puedo ocasionar problemas con el funcionamiento actual?» + elección de rama: «Acá mismo, en la rama actual».
- **L6** — «Si» (autoriza el escaneo read-only sobre `/Volumes/wupm/2026` y el commit 1 del retiro).
- **L7 (evidencia)** — `rutas.py` no importa `rutas_global` en ninguna línea: la dependencia es unidireccional (el panel consume el core del nodo). El corte no toca la lógica del nodo.
- **L8 (evidencia)** — Los cambios sin commitear de `registro.py` son 27 líneas de solo adición, todas de fSpy, en 4 regiones disjuntas del bloque del panel. El retiro se hace aislado con `git stash` por path y `git stash pop` posterior.
- **L9 (evidencia)** — El hook de arranque corre una sola vez por sesión y en ese momento no hay comp abierto, así que su paso de recarga de Reads es un no-op; su efecto real es setear `__main__.PYTHON_*` y disparar `proyecto.cargar_scripts_proyecto()`.
