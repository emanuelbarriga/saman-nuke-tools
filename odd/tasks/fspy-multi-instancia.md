# Feature: fSpy multi-instancia

El panel fSpy deja de ser un singleton por grupo: se pueden crear varios paneles en el mismo comp, cada uno con sus propios artefactos generados.

## Specs

- **S1** — El pedido original, textual: «Hay algo bloqueante, que solo deja crear un solo nodo fspy, por qué?» y la autorización de arreglarlo: «Si».
- **S2** — Causa raíz confirmada: `fspy.crear_o_reutilizar()` busca un nodo por **nombre fijo** (`fSpy`) en el grupo actual y enfoca el existente en vez de crear otro. Ese guard es la causa del bloqueo, no una limitación de Nuke.
- **S3** — Razón estructural del guard: los nodos generados usan nombres fijos (`fSpy_cam`, `fSpy_cube`, `fSpy_read`) y `_nuevo()` **borra** cualquier nodo previo con ese nombre. Dos paneles en el mismo grupo se destruirían mutuamente.
- **S4** — Nuevo comportamiento: el menú y el buscador TAB **siempre crean** un panel nuevo. `crear_o_reutilizar` deja de reutilizar (se renombra a `crear` o se elimina el guard), y su docstring deja de prometer «máximo 1».
- **S5** — Los nombres de los artefactos se derivan del **nombre del panel**: un panel `fSpy` genera `fSpy_cam` / `fSpy_cube` / `fSpy_read` (idéntico a la versión actual, compatibilidad total con los comps ya guardados); un panel `fSpy1` genera `fSpy1_cam` / `fSpy1_cube` / `fSpy1_read`.
- **S6** — `_borrar`, `_construir_nodos`, `_camara`, `_cubo` y `_leer_imagen` usan el mismo prefijo derivado. Construir el segundo panel NO puede tocar los artefactos del primero.
- **S7** — Limitación documentada, no silenciosa: si el artista **renombra** el panel después de construir, un nuevo «Construir» genera artefactos con el prefijo nuevo y los anteriores quedan huérfanos. Debe estar dicho en el docstring, no descubrirse por accidente.
- **S8** — Cobertura obligatoria: `fspy.py` no tenía ningún test. `tests/test_fspy_nodos.py` (nuevo, con el stub de `nuke` de `conftest.py`) prueba como mínimo: (a) el primer panel genera los nombres históricos; (b) un segundo panel genera nombres con su propio prefijo; (c) construir el segundo no borra ni sobrescribe los artefactos del primero; (d) `_borrar` borra solo los del panel que lo invoca; (e) `_insertar_fspy` crea un panel nuevo aunque ya exista uno.
- **S9** — Sin regresión: la suite completa sigue verde y `py_compile` pasa en todo archivo tocado. El docstring de `registro._insertar_fspy` deja de decir «máximo uno por contexto, igual que Rutas».
- **S10** — El dist se regenera y el manifiesto declara el test nuevo entre los tests del componente `fspy`.

## Tasks

| ID | Specs | Ruta | Commit |
| --- | --- | --- | --- |
| T1 | S2, S3, S4, S6, S7 | `SamanTools/fspy.py`: fuera el singleton, prefijo derivado del panel, docstrings | pendiente |
| T2 | S8 | `tests/test_fspy_nodos.py`: nombres históricos, segundo panel aislado, `_borrar` propio, `_insertar_fspy` siempre crea | pendiente |
| T3 | S9, S10 | `registro.py` docstring + `componentes.py` con el test nuevo + dist regenerado | pendiente |

## Log

- **L1** — «Hay algo bloqueante, que solo deja crear un solo nodo fspy, por qué?».
- **L2** — «Si» (autoriza el arreglo).
- **L3 (evidencia)** — `fspy.py:48-55` busca por nombre fijo en `nuke.thisGroup()` y enfoca el existente. `fspy.py:358-365` (`_nuevo`) borra el nodo con el nombre destino antes de crear. Ambas piezas son las que hacen inviable tener dos paneles.
- **L4 (evidencia)** — `fspy.py` tiene 365 líneas y ningún test propio; solo `fspy_core.py` está cubierto (`tests/test_fspy_core.py`, 17 tests). Por eso S8 exige tests antes de dar el cambio por bueno.
