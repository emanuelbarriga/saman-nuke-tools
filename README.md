# saman-nuke-tools

Herramientas globales de Nuke para el estudio (multiplataforma: macOS, Windows, Linux).
Incluye los nodos **Breakdown**, **Review**, **Rutas** y el menú **SamanTools** (ChangeColorspace).

## Qué contiene

```
saman-nuke-tools/
├── menu.py                  # bootstrap que carga SamanTools al arrancar Nuke
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
├── install.sh               # instalador macOS/Linux
├── install.bat              # instalador Windows
└── .gitignore
```

## Instalación (2 opciones)

### Opción A — Clonar + NUKE_PATH (recomendada, sin copiar)

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

## Cómo se verifica

Tras reiniciar Nuke:
- Aparece el menú **SamanTools** (Utilidades / Insertar Nodo).
- En el buscador (TAB), escribiendo **breakdown**, **review** o **rutas** se crean los nodos.

## Rutas de red (importante)

Las rutas de red (`PYTHON_COMP/FROM/TO`) NO están versionadas. Cada usuario configura
sus propios paths (variables de entorno o el nodo Rutas). No edites rutas absolutas en
los `.gizmo` — usan expresiones `\[python {PYTHON_...}]` dinámicas.

## Requisitos

- Nuke 15+ (los enums PySide6 del widget Breakdown requieren Nuke 14+).
- Git.
