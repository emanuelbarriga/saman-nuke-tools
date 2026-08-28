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

## Instalación — 3 opciones

### Opción C — Auto-update via GitHub (RECOMENDADA para artistas)

Los artistas ejecutan **una sola vez** el setup y a partir de ahí las
actualizaciones les llegan solas al reiniciar Nuke (git pull silencioso,
máximo 1 vez cada 6 h). No tocan nada nunca más.

**Requisito:** el repo debe estar publicado en GitHub (público o con acceso de
lectura para los artistas). El `menu.py` bootstrap vive en `bootstrap/menu.py`.

```bash
# macOS/Linux — una sola vez por artista
bash setup_artista.sh https://github.com/TU_ORG/saman-nuke-tools.git

# Windows — una sola vez por artista
setup_artista.bat https://github.com/TU_ORG/saman-nuke-tools.git
```

**Para actualizar a todos los artistas:** el mantenedor hace commit + push a
`main`. Los artistas reciben el cambio en su próximo arranque de Nuke.

> ¿Cómo funciona? `~/.nuke/menu.py` (bootstrap mínimo) clona el repo a
> `~/.nuke/SamanTools`, hace `git pull` con rate-limit de 6 h, y carga el
> `menu.py` real del checkout. Si no hay red, usa la copia local sin romper Nuke.

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
