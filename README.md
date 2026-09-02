# saman-nuke-tools

Herramientas globales de Nuke para el estudio (multiplataforma: macOS, Windows, Linux).
Incluye los nodos **Breakdown**, **Review**, **Rutas** y el menú **SamanTools** (ChangeColorspace).

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

> La copia manual funciona (menú + nodos + nodo Rutas), pero como el `git fetch`
> no puede salir a GitHub, **no habrá aviso de actualizaciones**: para actualizar
> repetí la copia con la versión nueva (o corré `git pull` cuando haya red).

## Actualizaciones (modelo actual)

El mantenedor hace **commit + push** a `main`. En cada equipo:

- El bootstrap hace `git fetch` al arrancar (no modifica nada) y compara.
- **Hay versión nueva** → alerta "¿Querés actualizar ahora?" (Sí/No).
- El botón **SamanTools ▸ Actualizar SamanTools...** funciona a demanda y
  también **reinstala** si el checkout falta.
- Solo con consentimiento se ejecuta `git pull --ff-only`.
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
- Aparece el menú **SamanTools** plano: Cambiar ColorSpace, Breakdown, Panel de Comentarios (`Ctrl+Alt+C`), Diagnóstico de Red, **Panel de Rutas** y el submenú **Configuración** (mantenimiento).
- El **Panel de Rutas** es la config global de rutas (`~/.config/saman/rutas_global.json`); aplica `PYTHON_TO_VFX/COMP/FROM_VFX` al arrancar. El nodo Rutas legacy sigue funcionando por compatibilidad (coexistencia), y el panel permite **Importar desde nodo** para migrar. El día del reemplazo solo se elimina el adaptador del nodo (ver `rutas_global.py`).
- En el buscador (TAB), escribiendo **breakdown**, **review** o **rutas** se crean los nodos.

## Rutas de red (importante)

Las rutas de red (`PYTHON_COMP/FROM/TO`) NO están versionadas. Cada usuario configura
sus propios paths (variables de entorno o el nodo Rutas). No edites rutas absolutas en
los `.gizmo` — usan expresiones `\[python {PYTHON_...}]` dinámicas.

## Requisitos

- Nuke 15+ (los enums PySide6 del widget Breakdown requieren Nuke 14+).
- Git.
