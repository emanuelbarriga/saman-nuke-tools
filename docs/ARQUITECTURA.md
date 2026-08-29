# Arquitectura y puntos clave de SamanTools

Documento vivo: compila las decisiones de diseño, errores históricos,
flujo de actualización y estado del repo. Si tocas este proyecto, leelo
primero.

Última actualización: 2026-08-28.

---

## 1. Qué es

Toolkit global de Nuke para el estudio **Samán Estudio**:

- **Nodos globales**: Breakdown (widget de frames), Review (comparación), Rutas (rutas VFX dinámicas).
- **Menú SamanTools** en la barra superior: Utilidades / Insertar Nodo / Acerca de / Actualizar / Desinstalar.
- Multiplataforma: macOS, Windows, Linux.
- Fuente de todo: repo público `emanuelbarriga/saman-nuke-tools` en GitHub.

---

## 2. Arquitectura de las piezas

```
[Artista]                            [Mantenedor]
  ~/.nuke/menu.py (bootstrap)          edita repo + push
        │  git fetch (ver alerta)                 │
        ▼                                         ▼
  ~/.nuke/SamanTools (checkout git) <─── GitHub (main)
        │  nuke.pluginAddPath(SamanTools/nodos)
        ▼
  SamanTools/registro.py → menú Nuke
```

### Piezas y responsabilidades

| Pieza | Rol |
|---|---|
| `bootstrap/menu.py` | El `menu.py` del artista (copiado a `~/.nuke`). Mantenimiento: alerta de update, botones Actualizar/Desinstalar, auto-sincronización del bootstrap mismo. **Nunca depende del código del repo** (funciona aunque el repo esté roto). |
| `menu.py` (raíz) | Carga real: `sys.path`, `pluginAddPath`, `registro.instalar()`. Se ejecuta vía `exec` desde el bootstrap. |
| `SamanTools/registro.py` | Construye el menú SamanTools + buscador TAB. |
| `SamanTools/proyecto.py` | Carga dinámica de galerías/gizmos del proyecto (`{PYTHON_COMP}/Scripts`). |
| `SamanTools/rutas.py` | Lógica del nodo Rutas: actualiza `PYTHON_COMP/FROM/TO` y reload selectivo. |
| `instalar_script_editor.py` | Instalador desde cero (Script Editor). Idempotente: detecta 3 estados. |
| `setup_artista.sh/.bat` | Instalador por terminal, autocontenido vía `curl\|bash` o desde checkout. |

---

## 3. Modelo de actualización (el artista decide)

**Principio**: nunca se fuerza un update. El artista consiente.

1. Al arrancar, el bootstrap hace solo `git fetch` (no modifica nada) y compara HEAD vs `origin/main`.
2. Si hay versión nueva → alerta `nuke.ask("¿Querés actualizar ahora?")` (máx. 1 vez cada 6 h — `LOCK_FILE`).
3. El botón **SamanTools ▸ Actualizar SamanTools...** consulta a demanda y, si no hay checkout, **reinstala** (clone limpio).
4. Solo con consentimiento se ejecuta `git pull --ff-only`.
5. El bootstrap se **auto-actualiza** en cada arranque: compara hash de `~/.nuke/menu.py` vs `bootstrap/menu.py` y se reemplaza solo si difieren.

### Estados posibles

| Estado | Comportamiento |
|---|---|
| Checkout completo + red | Carga el menú; alerta si hay update. |
| Checkout completo sin red | Carga la copia local; sin alerta. |
| Checkout incompleto (clone/pull a medias) | `git reset --hard origin/main` automático; si falla, carga local. |
| Sin checkout (desinstalado / nunca instalado) | **Silencio total**: sin menú, sin errores. Solo botones via bootstrap. |
| Sin checkout + botón Actualizar | Reinstala desde GitHub (previo consentimiento). |

---

## 4. Errores históricos (lecciones grabadas)

Estos bugs se corrigieron; **no reintroducirlos**:

1. **`nuke.Undo("nombre")` → TypeError** — la versión de Nuke del estudio NO acepta argumento en `nuke.Undo()`. Usar siempre `nuke.Undo()`.
2. **`nuke.pluginAddPath(dir, addToMenuBar=False)` → TypeError** — misma versión no soporta ese kwarg. Usar `pluginAddPath(dir)` a secas.
3. **`padding_fix()` inexistente** — el fallback `/Volumes/` del botón Rutas llamaba una función que no existía → `NameError` latente. Se eliminó usando `partes[3]` directo.
4. **Clone sobre directorio no vacío falla en silencio** — `git clone` a una carpeta con instalación vieja por-copia falla con "already exists and is not an empty directory", y el `DEVNULL` ocultaba el error → `copy2` reventaba después. El instalador actual usa **clone a temporal + rename** (`clonar_limpio`).
5. **Pull silencioso rompía la red de seguridad** — el auto-update original aplicaba sin consentimiento; se reemplazó por alerta + confirmación.
6. **Desinstalar acumulaba respaldos** — la versión vieja "movía a respaldo"; se cambió a **borrar definitivo** (`shutil.rmtree`), sin dejar nada.
7. **Bootstrap que no se auto-actualizaba** — los botones del bootstrap solo se copiaban al instalar; ahora se auto-sincroniza por hash.
8. **Ciclo infinito desinstalado→error** — el arranque intentaba clonar sin red y dejaba checkout parcial con `.git`; ahora el arranque NO clona y el estado sin checkout es silencio.

---

## 5. Versionado y releases

Ver `VERSIONING.md`. Resumen:

- Fuente única: `SamanTools/__init__.py` → `__version__` (SemVer).
- Reglas: PATCH = fix; MINOR = función compatible; MAJOR = incompatibilidad.
- Release: bump `__version__` → commit → `git tag v<version>` → `git push origin main --tags`.
- El tag debe coincidir con `__version__` (lo verifica `verificar_salud.py`).

---

## 6. Calidad y cobertura

Suite pytest en `tests/` (24 tests, PASS) + stub de `nuke` en `conftest.py`.

| Módulo | Cobertura | Nota |
|---|---|---|
| `rutas.py` | 97% | Lógica crítica: reload solo si la ruta resuelta cambió. |
| `cambiar_colorspace.py` | 71% | Parseo OCIO (`\t` vs `,`). |
| `proyecto.py` | 57% | Clasificación Galerías/Herramientas, escaneo, rutas. |
| `registro.py` | 0% | UI Nuke, sin lógica pura testeable. |
| `frame_manager.py` | 0% | Widget Qt, depende de Nuke/Qt runtime. |

**Regla**: no falsear cobertura. `registro.py`/`frame_manager.py` en 0% es aceptable (UI); la skill reporta el número real.

### Indicador de salud

`skills/saman-nuke-tools-maintenance/assets/verificar_salud.py` (o `.opencode/skills/...`) reporta:
versión/tag, sync git, checks estructurales (35), pytest PASS/FAIL, cobertura %, symlinks de skills.

---

## 7. Formato de espacios de color OCIO

`nuke.getOcioColorSpaces()` devuelve: `"id_interno\tid_interno (descripcion)"`.

- El **ID técnico va PRIMERO** (`scene_linear`), la descripción visible al final.
- El parser usa `partes[0]` = id, `partes[-1]` = visible. No invertir.

---

## 8. Reglas operativas

1. **El repo es público** — nunca commitear secretos, tokens, rutas absolutas personales ni `config_local.py` (ignorado).
2. **Validar siempre** `python3 -m py_compile` sobre todo `.py` tocado antes de commit.
3. `install.sh`/`install.bat` son **legacy** — no tocarlos; el flujo actual es `instalar_script_editor.py` + `bootstrap/menu.py`.
4. **Skills del estudio** viven versionadas en `skills/`; el proyecto HTLR las enlaza por symlink (`.opencode/skills/<name> → repo/skills/<name>`). Editar siempre en el repo, nunca en el copia local.
5. Para regenerar el skill registry: `gentle-ai skill-registry refresh` (el registro apunta a `.opencode/skills`, que resuelve al repo vía symlinks).