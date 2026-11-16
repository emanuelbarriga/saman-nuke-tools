# saman-nuke-tools

Herramientas globales de Nuke para el estudio (multiplataforma: macOS, Windows, Linux).
Versión actual: **2.0.0**. Incluye los nodos **Breakdown**, **Review**, **Rutas**, **fSpy** y el menú **SamanTools** (ChangeColorspace).

> **Antes de tocar el código**: lee [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md) —
> decisiones de diseño, flujo de actualización, errores históricos y reglas operativas.

## Qué contiene

```
saman-nuke-tools/
├── menu.py                  # bootstrap que carga SamanTools al arrancar Nuke
├── instalar_script_editor.py# INSTALADOR desde cero (pegá en el Script Editor)
├── bootstrap/
│   └── menu.py              # menu.py de mantenimiento (Actualizar/Desinstalar)
├── SamanTools/
│   ├── registro.py          # registra menú superior + buscador TAB
│   ├── proyecto.py          # carga dinámica de galerías del proyecto
│   ├── rutas.py             # variables PYTHON_COMP/FROM/TO
│   ├── rutas_global.py      # config global aplicada por el hook de arranque
│   ├── fspy.py / fspy_core.py
│   ├── fSpy.svg             # icono de fSpy
│   ├── cambiar_colorspace.py
│   ├── frame_manager.py     # widget Qt del nodo Breakdown (tabla de frames)
│   ├── nodos/
│   │   ├── Breakdown.gizmo  # VFX breakdown (tabla de frames + capas)
│   │   ├── Review.gizmo     # comparación side-by-side
│   │   ├── Rutas.gizmo
│   │   └── Rutas.nk
├── setup_artista.sh         # instalador autocontenido macOS/Linux
├── setup_artista.bat        # instalador Windows
├── install.sh / install.bat # (legacy: copia a ~/.nuke)
└── VERSIONING.md
```

## Instalación — desde cero (REINSTALAR / PRIMERA VEZ)

Requisito en todas las vías: **Git instalado** (https://git-scm.com/downloads)
y acceso a GitHub. El instalador usa `git clone` — es la vía más fiable.

> **En Linux** el instalador crea `~/.nuke/SamanTools` (el checkout) y
> `~/.nuke/menu.py` (el bootstrap); `~/.nuke` es `/home/<usuario>/.nuke`.
> Elegí la vía según la red: con GitHub libre → Opción 1 o 2; si la red
> bloquea `raw.githubusercontent.com` → Opción 3; si no llega a GitHub →
> copia manual al final.

### Opción 1 — Script Editor de Nuke (RECOMENDADA, sin terminal)

En **cualquier equipo** (macOS/Windows/Linux), desde cero o después de una
desinstalación:

1. Abre Nuke → **Script Editor** (menú *View ▸ Script Editor* o tecla `W`).
2. Pega el contenido de [`instalar_script_editor.py`](instalar_script_editor.py)
   (está en la raíz del repo) y ejecuta con `Ctrl+Enter`.
3. Según el estado: clona desde cero, actualiza el checkout existente, o
   migra una instalación vieja por-copia. Luego copia el bootstrap a `~/.nuke/menu.py`.
4. Reinicia Nuke → aparece el menú **SamanTools**.

### Opción 2 — Terminal (curl | bash)

Solo en redes donde `raw.githubusercontent.com` sea accesible (no en todas):

```bash
# macOS / Linux
curl -sL https://raw.githubusercontent.com/emanuelbarriga/saman-nuke-tools/main/setup_artista.sh | bash

# Windows (PowerShell) — requiere Git for Windows
Invoke-WebRequest -UseBasicParsing https://raw.githubusercontent.com/emanuelbarriga/saman-nuke-tools/main/setup_artista.sh -OutFile setup_artista.sh
bash setup_artista.sh
```

### Opción 3 — Desde un checkout local (red corporativa que bloquea raw.githubusercontent.com)

Útil cuando el firewall del estudio bloquea `raw.githubusercontent.com` pero
permite `github.com`, o si llevás el repo en una USB / red interna:

```bash
git clone https://github.com/emanuelbarriga/saman-nuke-tools.git
cd saman-nuke-tools && ./setup_artista.sh    # macOS/Linux
cd saman-nuke-tools && setup_artista.bat     # Windows
```

El instalador detecta el bootstrap local y no descarga nada por curl.

### Sin NINGÚN acceso a GitHub (copia del checkout completo)

Si la máquina tampoco llega a `github.com`, cloná el repo en otra máquina con
internet, copiá la carpeta **completa (con `.git`)** por USB / red interna y
armá la instalación:

```bash
# 1) En la máquina con internet:
git clone https://github.com/emanuelbarriga/saman-nuke-tools.git

# 2) Copiá TODO el checkout (incluida la carpeta .git) a la máquina Linux:
#    USB / red interna / scp
#    IMPORTANTE: sin .git el bootstrap cree que NO hay instalación y no carga el menú.

# 3) En la máquina Linux:
mkdir -p ~/.nuke
cp -r saman-nuke-tools ~/.nuke/SamanTools
cp ~/.nuke/SamanTools/bootstrap/menu.py ~/.nuke/menu.py
```

> La copia manual funciona (menú + nodos + nodo Rutas), pero como el `git pull`
> no puede salir a GitHub, **no se auto-actualizará**: para actualizar
> repetí la copia con la versión nueva (o corré `git pull` cuando haya red).

## Actualizaciones (modelo actual)

El mantenedor hace **commit + push** a `main`. En cada equipo:

- El bootstrap hace `git pull --ff-only --quiet` al arrancar e **aplica sola la
  última versión** (push automático), antes de construir el menú.
- **Seguro**: con `--ff-only` NO avanza si el árbol local está sucio o divergió;
  mantiene la copia local y el botón **SamanTools ▸ Actualizar SamanTools...**
  sigue como respaldo (y **reinstala** si el checkout falta).
- Sin red → usa la copia local sin romper Nuke. Desinstalado → sin menú.

### Opción A — Clonar + NUKE_PATH (sin copiar)

1. Clona el repo donde quieras:
   ```bash
   git clone <URL> saman-nuke-tools
   ```
2. Añade la carpeta del repo a `NUKE_PATH`:
   - **macOS/Linux**: añade a `~/.bash_profile` / `~/.zshrc`:
     ```bash
     export NUKE_PATH="/ruta/a/saman-nuke-tools:$NUKE_PATH"
     ```
   - **Windows**: variable de entorno de usuario `NUKE_PATH` con el valor `C:\ruta\samane-nuke-tools`
3. Reinicia Nuke. `menu.py` carga desde la carpeta del repo automáticamente.

> Actualizar = `git pull` y reiniciar Nuke. No se copia nada.

### Opción B — Copiar a ~/.nuke

```bash
# macOS/Linux
cd saman-nuke-tools && ./install.sh

# Windows
cd saman-nuke-tools && install.bat
```

> Actualizar = `git pull && ./install.sh` (o `.bat`).

## Distribución verificable

La distribución se genera desde la fuente única con:

```bash
python3 -m SamanTools.build_dist
```

El resultado queda en `dist/samantools/` e incluye `MANIFIESTO.md` con los componentes y sus tests asociados. `dist/` está en `.gitignore`: es un artefacto generado y no se edita a mano.

## Skills del estudio (versionadas aquí)

Las skills de OpenCode/Claude usadas por el estudio viven versionadas en
[`skills/`](skills/) para que no se pierdan y viajen con el repo:

| Skill | Para qué |
|---|---|
| `nuke-project-clone` | Clonar el template SAMAN de Nuke para un nuevo shot/episodio |
| `nuke-gallery-gizmo` | Construir galerías de assets (contact sheets) desde GLOBAL_ASSETS |
| `nuke-breakdown-gizmo` | Crear/regenerar el widget de VFX breakdown (tabla de frames) |
| `saman-nuke-tools-maintenance` | Mantener este repo: versión, tags, sync git, cobertura de tests |

> Las skills `nuke-*` son del proyecto HTLR y referencian rutas de esa
> máquina (`/Volumes/wupm/2026/HTLR/...`) — sirven como fuente versionada,
> no como distribución a artistas.

## Cómo se verifica

Tras reiniciar Nuke:
- Aparece el menú **SamanTools** con **Acerca de**, **Breakdown**, **fSpy** y **Actualizar** directos; los submenús son **Tools** (Cambiar ColorSpace), **Paneles (En construcción)** (Panel de Comentarios con `Ctrl+Alt+C`) y **Salud** (Diagnóstico de Red, Verificar Salud, Escanear Scripts, Limpiar knobs). **Desinstalar** queda al final (mantenimiento).
- `rutas_global.py` conserva la configuración global de rutas en `~/.config/saman/rutas_global.json`. El hook de arranque de `registro.py` la consume, mediante `_componente_disponible`, para aplicar `PYTHON_TO_VFX/COMP/FROM_VFX`; no es una interfaz de usuario. El nodo Rutas sigue siendo la herramienta para configurar rutas en el comp.
- fSpy usa el icono `SamanTools/fSpy.svg` en el menú SamanTools y en el menú Nodes.
- En el buscador (TAB), escribiendo **breakdown**, **review**, **rutas** o **fSpy** se crean los nodos.

## Rutas de red (importante)

Las rutas de red (`PYTHON_COMP/FROM/TO`) NO están versionadas. Cada usuario configura
sus propios paths (variables de entorno o el nodo Rutas). No edites rutas absolutas en
los `.gizmo` — usan expresiones `\[python {PYTHON_...}]` dinámicas.

## Requisitos

- Nuke 15+ (los enums PySide6 del widget Breakdown requieren Nuke 14+).
- Git.
