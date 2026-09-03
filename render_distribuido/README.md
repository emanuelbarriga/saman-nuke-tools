# Orquestador de render distribuido

La infraestructura del orquestador (workers, bases por SO, sufijos y proyectos
habilitados) NO vive en el codigo: se resuelve en runtime desde la config
central estricta `render_config.obtener_config_efectiva()`. El CLI solo puede
sobreescribir sufijos por corrida y seleccionar nodos/layout por flags.

## Donde vive la config real

`{base}/.saman/studio_config.json` — la base la resuelve
`entorno.primera_ruta_disponible()` (storage montado) o la variable
`RENDER_CONFIG_BASE` (gana, salta el gate de montaje).

- **Plantilla publica**: `studio_config.example.json` (este directorio).
  Copiala a `{base}/.saman/studio_config.json` y completa con los datos
  reales del estudio (workers, bases por SO, sufijos, `proyectos`). La
  plantilla usa hostnames, rutas y sufijos FICTICIOS — nunca versiones el
  archivo real.
- **`proyectos`**: mapa nombre->bool (aditivo). Un proyecto solo resuelve su
  layout si esta habilitado aqui; la ausencia de la clave es valida (configs
  legacy siguen cargando).
- **Override por maquina**: `config_local.py` con `RENDER_LOCAL_CONFIG`
  (dict con las MISMAS llaves del esquema, gitignored). Sus valores ganan
  por llave a los del JSON.

## Politica estricta

Sin base, o con el JSON ausente/invalido y sin `RENDER_LOCAL_CONFIG`
completo, la carga ABORTA con instrucciones (copiar la plantilla o revisar
montaje/red). Nunca hay defaults silenciosos. Un `RENDER_LOCAL_CONFIG`
completo rescata la ausencia del disco: autonomia por nodo. Una carpeta de
planos sin `.nk` calificante (o un plate ausente) tambien aborta NOMBRANDO
la carpeta/ruta.

## Convencion multi-proyecto: roles fijos, layout = dato

Los **roles semanticos** (PLATE, DELIVERY, PREVIEW, SBS) son contrato de
dominio y quedan fijos en codigo. El **layout fisico** (episodios, fechas,
naming de comps) NO es fijo: cada proyecto declara sus propios patrones
RELATIVOS como datos en `render_distribuido/layouts.py`, resueltos contra la
base del config para los proyectos habilitados. Cero raices absolutas, cero
IPs, cero tokens usuario-host en los datos (guard `tests/test_no_fuga.py`).

| Proyecto | Episodio/Secuencia | Comps (`COMP/...`) | Plate | Entrega |
|---|---|---|---|---|
| HTLR | episodios `EP_n` ("Capitulo 7" -> `EP_07`) | `<plan>_comp_SAMAN_V###/` | `TO_VFX/{ep}/{fecha}/{plan}.mov` | `FROM_VFX/{ep}/{fecha}/{tipo}/` |
| IPYD | episodios numericos `101..106` | naming `IPYD_*_COMP_SAMAN_SE` (sin `_V`) | `TO_VFX/{ep}/{fecha}/{plan}.mov`, fechas `YYYYMMDD[-N]` (ej. `20260628-2`) | `FROM_VFX/{ep}/{fecha}/{tipo}/` |
| PCF | secuencias `PFC_SC##` (`SC13` -> `PFC_SC13`) | `<plan>_comp_SAMAN_V###/` | `FROM_VFX/{ep}/{fecha}/{plan}.mov`; alternativa `ENTREGAS/COMP/SC##/` | `FROM_VFX/{ep}/{fecha}/{tipo}/` |

## ACL de `{base}/.saman/studio_config.json` (LucidLink, D8)

- **WRITE**: solo admin.
- **READ**: los `ssh_user` de los workers (minimo: grupo/maquinas de render).
  La config es infraestructura, no secreto: los nodos de render deben poder
  leerla.
- **Fallback operativo**: si un nodo no puede leer el JSON, se le distribuye
  la config COMPLETA en `config_local.py` (`RENDER_LOCAL_CONFIG`) en ese
  nodo (autonomia local sin disco ya soportada).
- **Criterio de verificacion**: un usuario worker puede ejecutar
  `cat {base}/.saman/studio_config.json`, o el nodo tiene
  `RENDER_LOCAL_CONFIG` completo.

## Como crear la config

1. Copia `studio_config.example.json` a `{base}/.saman/studio_config.json`.
2. Completa `bases_por_so` (una ruta por SO de los nodos de render),
   `workers` (nombre, ssh host o null, ssh_user, nuke_exec, base, lc_all),
   `sufijos` y `proyectos` (habilitar HTLR/IPYD/PCF segun corresponda).
3. Verifica en el panel de LucidLink que admin tiene WRITE y que los
   `ssh_user` de los workers tienen READ del archivo (antes del rollout).
4. Opcional: `config_local.py` para overrides por maquina.

El esquema se valida en la carga: llaves obligatorias faltantes o tipos
incorrectos abortan listando TODAS las fallas con guia de arreglo (key path).

## Uso del orquestador

### Flujo legacy (sin flags nuevos)

La infraestructura sale de la config; los sufijos se pueden sobreescribir
por corrida:

```
python3 render_distribuido.py --comp RUTA_AL_COMP.nk \
    --wnode DELIVERY_EXR --auto-range \
    [--to-suf SUF] [--comp-suf SUF] [--from-suf SUF] [--workers a,b]
```

Bases multi-SO: el orquestador traduce templates entre TODAS las bases
declaradas (`bases_por_so`) para detectar frames existentes aunque el worker
reporte otra base (Windows/Linux hacia la base local y viceversa). Rutas
fuera de los prefijos declarados pasan intactas. El flujo legacy NO activa
layout ni gate QC (backward compat).

### Flujo asistido (layout + mtime + multi-nodo + gate QC)

```
python3 render_distribuido.py \
    --proyecto HTLR --comp-dir "Capitulo 7" --resolve-latest \
    --wnodes DELIVERY_EXR,REVIEW_REC709
```

1. **Seleccion por mtime real**: `mejor_version_comp` elige el `.nk` de mayor
   mtime del SO (medido en el orquestador, nunca en workers; LucidLink
   colapsa ctime/birthtime), ignorando `.nk~`/`.autosave`/temporales; `_V`
   es solo tie-break. Si la elegida por mtime NO es la de mayor `_V`, se
   marca `sospechosa` -> el artista confirma o elige [Usar v015].
   `--resolve-latest` confirma sin prompt; `--use-version V015` fuerza.
2. **Multi-nodo**: la PROBE descubre los Write reales del comp
   (`DELIVERY_EXR`, `DELIVERY_DWG`, `REVIEW_REC709`, `SBS_REC709`);
   `--wnodes` filtra. Existencia por tipo: EXR por frame, MOV por archivo.
   CALIB/PLAN solo sobre `DELIVERY_EXR`; los previews piggyback en el mismo
   batch del delivery respetando `use_limit`; `--force-exr` obliga salida
   EXR-sequence del nodo de entrega conservando duracion/resolucion. Los
   nombres son SIEMPRE los reales del comp (nunca "delivery"/"preview").
3. **Gate QC pre-render (Regla de Oro)**: localiza el plate del layout (fecha
   mas reciente por `fecha_key`: `20260628-2` > `20260627`; override
   `--plate-date`), lo deep-probea con ffprobe (codec, bit depth, colorspace,
   resolucion, fps, frames) y compara contra el Root del comp y el template de
   entrega. Discrepancias: **error** en Root/entrega (frames/fps/res ->
   reescritura del nodo delivery a specs del plate via `qc_set`, abort salvo
   `--force-qc`) o **warning** en previews (drift como EP_108: 1558 vs 1665,
   no aborta). Emite `TEST_RENDER/qc_<proyecto>_<YYYYmmdd_HHMMSS>.json` +
   resumen stdout.
4. Render: calib -> plan -> render del delivery (+ previews piggyback).

### Flags del flujo asistido

| Flag | Que hace |
|---|---|
| `--proyecto` | Layout del proyecto (default HTLR, con aviso) |
| `--comp-dir` | Carpeta de planos relativa a la base, o intencion ("Capitulo 7" -> `EP_07`) |
| `--resolve-latest` | Confirma la seleccion por mtime sin prompt |
| `--use-version VN` | Fuerza esa version `.nk` (override del falso positivo mtime) |
| `--wnodes` | Filtra nodos descubiertos por nombre real |
| `--force-exr` | Nodo de entrega como EXR-sequence (conserva duracion/resolucion) |
| `--force-qc` | Gate QC: procede pese a discrepancias (el reporte se emite igual) |
| `--plate-date YYYYMMDD[-N]` | Fecha del plate (default: la mas reciente) |
| `--validar-solo-duracion` | Naming roto plate<->Write: prosigue validando solo duracion |
| `--fps-forzar FPS` | FPS a forzar en el delivery (24 vs 23.976) en vez de abortar |

### Caminos tristes (decisiones estructuradas, exit code 3)

El CLI NUNCA bloquea un run headless: ante una discrepancia bloqueante emite
por stdout un bloque `__DECISION__{"id","problema","opciones","default"}` y,
en modo auto, sale con **exit code 3 ("necesita decision")** — el agente
pregunta al artista y re-invoca con el override no interactivo. En TTY elige
el artista por stdin. Ids de decision: `fps_mismatch` (forzar_fps/cancelar),
`naming_roto` (validar_solo_duracion/abortar), `discrepancia_qc`
(forzar_qc/cancelar).

| Camino triste | Deteccion | Override |
|---|---|---|
| Falso positivo mtime | `sospechosa=True` (v001 tocado hoy vs v015 aprobado) | `--use-version V015` (default: mas reciente por mtime) |
| Multiplicidad de fechas de plate | `20260628-2` > `20260627` | `--plate-date YYYYMMDD[-N]` |
| Naming roto plate<->Write | id de plano normalizado no empareja | `--validar-solo-duracion` o abort |
| FPS 24 vs 23.976 | fps del plate vs root difieren | reescritura al fps del plate + `--fps-forzar` (o `--force-qc`); default: abort |

### Exit codes

| Code | Significado |
|---|---|
| 0 | OK (o nada que renderizar) |
| 1 | Abort / cancelacion explicita del artista |
| 3 | Necesita decision: bloque `__DECISION__` por stdout; preguntar y re-invocar con el override |