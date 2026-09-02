# Propuesta: Config central de infraestructura del orquestador de render (`render-config-central`)

## Intención

`render_distribuido/` (orquestador multi-máquina, hoy SIN trackear) hardcodea infraestructura sensible: IPs, usuarios SSH, bins de Nuke, bases `/Volumes/wupm/2026` y `/mnt/wupm/2026`, sufijos `/HTLR/...`. El repo es público en GitHub → fuga de inventario del estudio. Objetivo: extraer esa capa a `{base}/.saman/studio_config.json` (LucidLink, ACL admin-escribe/artistas-leen), con el MISMO mecanismo del patrón vfxflow en producción.

El mantenedor agrega dos exigencias: (1) la carga valida la INTEGRIDAD del esquema (no solo existencia), abortando con TODAS las llaves faltantes y tipos incorrectos; (2) estaciones mixtas Windows/Linux/macOS: las bases se declaran por worker/SO en la config (cualquier ruta, ej. `W:\`, `/media/wupm`, `/Volumes/wupm` — sin par hardcodeado `/mnt`↔`/Volumes`) y el orquestador traduce rutas entre TODAS las bases declaradas para detectar frames existentes en el destino.

## Alcance

### In Scope
- Carga: `entorno.primera_ruta_disponible()` → `{base}/.saman/studio_config.json` → override `config_local.py` (`RENDER_LOCAL_CONFIG`, gitignored).
- **Política estricta**: sin base / JSON ausente o inválido ⇒ abortar indicando copiar `studio_config.example.json` a `{base}/.saman/studio_config.json`. Sin degradación silenciosa.
- **Validación de esquema en carga**: llaves de primer nivel obligatorias `bases_por_so`, `workers`, `sufijos`; por worker `nombre`, `ssh` (host o None/local), `ssh_user`, `nuke_exec`, `base`, `lc_all` (obligatoria aunque tenga default). Llaves faltantes ⇒ `SystemExit` listando TODAS + cómo arreglarlas; tipo incorrecto (lista donde va string, etc.) ⇒ error claro.
- Refactor de `render_distribuido.py` + `render_worker.py`: WORKERS, bases por SO y sufijos salen del código a la config. Convenciones de dominio (PLATE, DELIVERY_EXR, `_comp_SAMAN_`, sufijos TO/COMP/FROM_VFX) quedan FIJAS en código (contrato del nodo Rutas).
- **Mapeo multi-plataforma transparente**: `bases_por_so` (o base por worker) declara CUALQUIER ruta por SO (ej. `W:\wupm`, `/media/wupm`, `/Volumes/wupm`), sin par hardcodeado; el cargador expone traducción de prefijos entre TODAS las bases declaradas (generaliza `template_local()`) para que el orquestador compare/detecte frames existentes aunque el worker reporte otra base.
- `studio_config.example.json` (plantilla SIN datos reales: workers nombre/ssh/bin/base/lc_all, bases por SO, sufijos) CONFORME al esquema — la valida el propio cargador — + README corto del patrón.
- Primer commit de `render_distribuido/` con la config ya aplicada (nunca se versiona el archivo con IPs).
- Tests pytest: esquema (faltantes/tipos/abort), traducción multi-SO, resolución, override local, abort estricto.

### Out of Scope
- Sanitizar lo ya versionado (Rutas.gizmo/nk, skills con rutas HTLR) → follow-up anotado.
- Cambiar convenciones de dominio ni UX del orquestador; instaladores legacy (`install.sh`/`install.bat`).

## Capacidades

> `openspec/specs/` está vacío; este cambio crea la primera spec.

### Nuevas Capacidades
- `render-config-central`: resolución de infraestructura del orquestador (workers, bases por SO multi-plataforma, sufijos) desde `{base}/.saman/studio_config.json`; validación de INTEGRIDAD del esquema en carga (llaves/tipos, abort completo); traducción de rutas entre todas las bases declaradas; política estricta y plantilla pública validable.

### Capacidades Modificadas
- Ninguna.

## Enfoque

Replicar `SamanTools/vfxflow_config.py` (import lazy de `entorno`, `_cargar_config_disco`, `_cargar_config_local`) con resolución estricta: módulo `render_config.py` que valida el esquema por niveles (primer nivel + por worker), acumula TODAS las llaves faltantes y errores de tipo antes de lanzar `SystemExit` con instrucciones de arreglo. Expone `traducir_ruta()` con prefijos derivados de `bases_por_so` (todas las bases, no solo `/mnt`↔`/Volumes`) para generalizar `template_local()`. Un test valida que el example cumple el esquema del cargador.

## Áreas Afectadas

| Área | Impacto | Descripción |
|------|---------|-------------|
| `render_distribuido/render_distribuido.py` | Modified | WORKERS/BASES hardcodeados → carga estricta; `template_local()` genérico sobre el mapa de bases |
| `render_distribuido/render_worker.py` | Modified | sufijos `/HTLR/...` vía env desde config |
| `render_distribuido/render_config.py` | New | resolución + validación de integridad (llaves obligatorias por nivel, tipos, abort con TODAS las faltantes) + `traducir_ruta()` multi-SO |
| `render_distribuido/studio_config.example.json` | New | plantilla pública sin datos reales, CONFORME al esquema (validable) |
| `render_distribuido/README.md` | New | patrón + cómo crear la config |
| `tests/test_render_config.py` | New | pytest (unit, stub sin Nuke): esquema, traducción multi-SO, override, abort |

## Riesgos

| Riesgo | Probabilidad | Mitigación |
|--------|--------------|------------|
| Fuga de IPs/usuarios al repo público | Med | example sin datos; config_local gitignored; grep `192.168`/`@` en revisión de PR |
| Orquestador inoperante sin config en disco | High (por diseño) | abort claro con instrucción de creación; example en README |
| Divergencia del patrón vfxflow | Low | reusar `entorno.primera_ruta_disponible` + misma carpeta `.saman` |
| Example desincronizado del esquema | Low | test que valida `studio_config.example.json` con el propio cargador |
| Traducción multi-SO incompleta / prefijos ambiguos | Med | mapa declarativo único en `bases_por_so` + tests por combinación de SO |

## Rollback

- Código: `git revert` del commit del orquestador (el example es plantilla).
- Config de producción: fuera del repo (LucidLink); restaurar JSON anterior.

## Dependencias

- `SamanTools/entorno.py` (`primera_ruta_disponible`) — ya en producción.
- Unidad LucidLink wupm montada en runtime.

## Criterios de Éxito

- [ ] `grep -r "192.168\|servermac\|saman@"` en trackeados → 0 coincidencias.
- [ ] Orquestador funciona leyendo `{base}/.saman/studio_config.json` (sin datos en repo).
- [ ] Config ausente ⇒ abort con mensaje de creación del archivo.
- [ ] Llave obligatoria faltante (1er nivel o worker) ⇒ abort listando TODAS las faltantes + cómo arreglarlas (test).
- [ ] Tipo incorrecto (lista donde va string) ⇒ abort con error claro (test).
- [ ] `studio_config.example.json` pasa la validación del cargador (test).
- [ ] Detección de frames en el destino funciona con worker en otra base (traducción de prefijos, test).
- [ ] Override `config_local.py` precede al JSON central.
- [ ] Suite verde: `python3 -m pytest`.