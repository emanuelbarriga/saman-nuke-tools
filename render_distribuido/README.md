# Config central del orquestador de render distribuido

La infraestructura del orquestador (workers, bases por SO y sufijos por
defecto) NO vive en el codigo: se resuelve en runtime desde la config central
estricta `render_config.obtener_config_efectiva()`. El CLI solo puede
sobreescribir los sufijos por corrida.

## Donde vive la config real

`{base}/.saman/studio_config.json` — la base la resuelve
`entorno.primera_ruta_disponible()` (storage montado) o la variable
`RENDER_CONFIG_BASE` (gana, salta el gate de montaje).

- **Plantilla publica**: `studio_config.example.json` (este directorio).
  Copiala a `{base}/.saman/studio_config.json` y completa con los datos
  reales del estudio (workers, bases por SO, sufijos). La plantilla usa
  hostnames, rutas y sufijos FICTICIOS — nunca versiones el archivo real.
- **Override por maquina**: `config_local.py` con `RENDER_LOCAL_CONFIG`
  (dict con las MISMAS llaves del esquema, gitignored). Sus valores ganan
  por llave a los del JSON.

## Politica estricta

Sin base, o con el JSON ausente/invalido y sin `RENDER_LOCAL_CONFIG`
completo, la carga ABORTA con instrucciones (copiar la plantilla o revisar
montaje/red). Nunca hay defaults silenciosos. Un `RENDER_LOCAL_CONFIG`
completo rescata la ausencia del disco: autonomia por nodo.

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
   `workers` (nombre, ssh host o null, ssh_user, nuke_exec, base, lc_all) y
   `sufijos`.
3. Verifica en el panel de LucidLink que admin tiene WRITE y que los
   `ssh_user` de los workers tienen READ del archivo (antes del rollout).
4. Opcional: `config_local.py` para overrides por maquina.

El esquema se valida en la carga: llaves obligatorias faltantes o tipos
incorrectos abortan listando TODAS las fallas con guia de arreglo (key path).

## Uso del orquestador

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
fuera de los prefijos declarados pasan intactas.