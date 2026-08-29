---
name: saman-nuke-tools-maintenance
description: "Trigger: saman nuke tools, saman-nuke-tools, mantener SamanTools, versión, release, tag, cobertura, tests SamanTools, salud del repositorio de herramientas globales de Nuke. Audita y mantiene el repo de herramientas globales de Nuke para que esté siempre versionado, sincronizado y estable."
license: Apache-2.0
metadata:
  author: "emanuelbarriga"
  version: "1.1"
---

## Activation Contract

Load this skill when working on `/Volumes/wupm/2026/saman-nuke-tools` (repo GitHub `emanuelbarriga/saman-nuke-tools`): versionar, publicar releases, auditar versión/sync, crear o evaluar tests, revisar cobertura, o "mantener en orden" el toolkit global de Nuke (Breakdown, Review, Rutas, SamanTools menu).

## Hard Rules

- **Fuente de verdad de versión**: solo `SamanTools/__init__.py` → `__version__` (SemVer).
- **Nunca versionar solo en `__version__`**: crear/comprobar también el tag `v<version>` y `git push origin main --tags`.
- **`install.sh`/`install.bat` son legacy**: no tocarlos salvo alineación explícita; el flujo actual es `instalar_script_editor.py` + `bootstrap/menu.py` + `setup_artista.sh/.bat`.
- **No falsear cobertura**: ejecutar indicadores reales; nunca afirmar "tests OK" sin archivos de test reales o reporte.
- **El repo público**: nunca commitear secretos, tokens, rutas absolutas personales ni `config_local.py` (ignorado).
- **Validar siempre**: `python3 -m py_compile` sobre todo `.py` tocado antes de commit.
- **No tocar lo que no aplica**: los `padding_fix`/`addToMenuBar` ya corregidos sirven como regla — no reintroducir kwargs no soportados por el Nuke del estudio.

## Estado actual del nodo Rutas (v1.1.x) — reglas operativas

- **`Rutas.nk` es la fuente única del nodo; `Rutas.gizmo` es un ESPEJO exacto**: ambos archivos deben tener el bloque `NoOp { ... }` byte a byte idéntico. Al tocar el nodo, regenerar el `.gizmo` con `sed -n '/^NoOp {/,$p' SamanTools/nodos/Rutas.nk > SamanTools/nodos/Rutas.gizmo` y comprobar `diff`.
- **La creación pasa SIEMPRE por `rutas.crear_o_reutilizar()`** (menú SamanTools y buscador TAB usan la misma función): máximo UN nodo Rutas por proyecto; si el nodo existe, lo enfoca (`_enfocar_nodo`: `zoomToFitSelected` + `showControlPanel`); si es de versión anterior, ofrece reconstruirlo in-place conservando proyecto/usuario/9 rutas/posición.
- **Identificación de nodo**: `es_nodo_rutas()` usa `UsuarioActivo` + `TO_VFX_SERVER_MAC/WINDOWS/ARTIST` (NO `RutaActual`, eliminado en v1.1.2). La "versión" del nodo la define `KNOBS_VERSION_ACTUAL` (SeccionEntorno/SO_Detectado/EstadoUnidad/UsuarioRecomendado).
- **Al cambiar la estructura del nodo**: actualizar `KNOBS_VERSION_ACTUAL` en `rutas.py`, regenerar el espejo `.gizmo`, y buscar TODAS las llamadas a `n["knob"]` — si un knob se elimina, quitarlas o hacerlas condicionales. **EL STUB DE TESTS NO ATRAPA ESTO**: `NodoFake.__getitem__` devuelve `KnobFake()` por defecto, pero en Nuke real `n["knobInexistente"]` lanza `ValueError` (bug real que pasó con RutaActual en v1.1.2).
- El nodo actual tiene la sección "Entorno y estado de unidad" ARRIBA de UsuarioActivo, solo informativa (SO detectado + estado de la unidad verde/rojo + usuario recomendado según SO), y los grupos WINDOWS/ARTIST ocultos por defecto (`+HIDDEN` en el archivo) — `_aplicar_visibilidad()` los muestra según `UsuarioActivo`.

## Decision Gates

| Situación | Acción |
|---|---|
| Fix de bug, sin API nueva | bump PATCH (1.0.1) |
| Función nueva compatible | bump MINOR (1.1.0) |
| Cambio incompatible/reorg | bump MAJOR + documentar |
| Commit pendiente, HEAD != origin/main | avisar y ofrecer `git push` |
| ¿Hay tests? | NO → reportar cobertura real `0` y sugerir crearlos |
| Checkout sucio | detenerse, revisar diff antes de cualquier bump |

## Execution Steps

1. Correr el índice de salud: `python3 skills/saman-nuke-tools-maintenance/assets/verificar_salud.py` (o la ruta instalada de la skill al repo) y leer TODAS las salidas.
2. Si `checks` < total o hay pendientes: resolver estructura/compilación/sync ANTES de tocar versión.
3. Si la tarea pide release: subir `__version__`, correr el índice de nuevo, crear tag `v<version>`, `git push origin main --tags`.
4. Si la tarea pide tests/cobertura: crear tests reales bajo `tests/` (no fingir), correrlos y reportar el resultado.
5. Reportar: versión, tag, sync git, checks OK/total, tests encontrados, cambios realizados.

## Output Contract

Siempre devolver:
- `version` actual y último tag (con verificación de coincidencia).
- Estado git: clean/dirty, HEAD vs origin/main.
- `checks_ok/total`, `pytest` (PASS/FAIL), `tests` (número real) y `cobertura` (%).
- Lista de acciones realizadas y las pendientes con causa concreta.

## References

- `assets/verificar_salud.py` — script de salud/indicadores (ejecutar primero).
- Repo: `/Volumes/wupm/2026/saman-nuke-tools/docs/ARQUITECTURA.md` — decisiones de diseño, errores históricos, reglas operativas.
- Repo: `/Volumes/wupm/2026/saman-nuke-tools/VERSIONING.md` — política SemVer.
- Repo: `/Volumes/wupm/2026/saman-nuke-tools/README.md` — flujos de instalación/actualización.
- Repo: `/Volumes/wupm/2026/saman-nuke-tools/instalar_script_editor.py` — instalador oficial.
- Repo: `SamanTools/rutas.py` — lógica del nodo Rutas (crear_o_reutilizar, es_nodo_rutas, es_version_actual, _enfocar_nodo, _aplicar_visibilidad) y `SamanTools/entorno.py` — detección de SO/unidad (no importa nuke, testeable).