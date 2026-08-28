# Versionado de SamanTools

Este proyecto usa **SemVer** (`MAJOR.MINOR.PATCH`).

La **única fuente de verdad** es `SamanTools/__init__.py` → `__version__`.

## Reglas

- **PATCH (1.0.1)** — fixes de bugs, cambios que no alteran comportamiento visible
  ni agregan funciones (ej: quitar `addToMenuBar=False`, corregir `padding_fix`).
- **MINOR (1.1.0)** — nueva funcionalidad compatible hacia atrás
  (ej: botón Actualizar, comando Acerca de, botón Desinstalar).
- **MAJOR (2.0.0)** — cambio incompatible o reorganización grande.

## Cómo publicar una versión

1. Edita `SamanTools/__init__.py` → sube `__version__`.
2. `git add -A && git commit -m "release: vX.Y.Z"`
3. `git tag vX.Y.Z && git push origin main --tags`

Los artistas ven la versión instalada en **SamanTools ▸ Acerca de SamanTools...**.