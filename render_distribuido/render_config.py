"""render_config - Config central estricta del orquestador de render.

Replica el patron vfxflow (SamanTools/vfxflow_config) con politica ESTRICTA:
sin fuente esquema-completa => SystemExit diferenciado. Cadena de resolucion:

    1. Base: env ``RENDER_CONFIG_BASE`` gana; si no,
       ``SamanTools.entorno.primera_ruta_disponible()`` (import lazy, shim de
       sys.path para correr como script - patron D del design).
    2. ``{base}/.saman/studio_config.json`` (LucidLink, lo escribe el admin).
    3. ``config_local.py`` con ``RENDER_LOCAL_CONFIG`` (dict gitignored con
       las MISMAS llaves del esquema): merge por llave sobre el JSON.

Politica estricta: ``FileNotFoundError`` (o archivo ausente tras el gate de
montaje) => "config missing" + sugerir copiar ``studio_config.example.json``;
``OSError``/``TimeoutError``/EIO o gate caido => fallo explicito de
conexion/montaje, JAMAS sugerir copiar la plantilla. Un local completo
rescata la ausencia del disco (autonomia, D8). El validador acumula TODAS
las llaves faltantes y tipos incorrectos en UN SystemExit con key path y
guia de arreglo.

TODO(T2/PR2): ``traducir_ruta``, ``detectar_so_de_ruta``, ``mapa_bases``,
``_canon`` y ``normalizar_separadores`` (spec: Multi-OS path translation) +
integridad D2 (worker.base debe caer bajo una base declarada de
``bases_por_so``); se implementan en la tarea T2, no en T1.
"""

import importlib
import json
import os
import subprocess
import sys

# Ruta del JSON central relativa a la base: {base}/.saman/studio_config.json.
ARCHIVO_DISCO = ".saman/studio_config.json"

# Env var que sobreescribe la base (salta el gate de montaje, D4).
ENV_BASE = "RENDER_CONFIG_BASE"

# Plantilla publica del esquema (se crea en T5); las guias la referencian.
ARCHIVO_EJEMPLO = "studio_config.example.json"

# Llaves obligatorias del esquema, por nivel (spec: Schema integrity).
LLAVES_PRIMER_NIVEL = ("bases_por_so", "workers", "sufijos")
LLAVES_WORKER = ("nombre", "ssh", "ssh_user", "nuke_exec", "base", "lc_all")
LLAVES_SUFIJOS = ("TO_VFX", "COMP", "FROM_VFX")

# Cache del import lazy de SamanTools.entorno (D5).
_entorno_mod = None


class _ErrorDisco(Exception):
    """Fallo al leer la config del disco: tipo faltante|montaje|invalido."""

    def __init__(self, tipo, ruta=None, detalle=""):
        super().__init__(tipo)
        self.tipo = tipo
        self.ruta = ruta
        self.detalle = detalle


# ---------------------------------------------------------------------------
# Resolucion de base y entorno (D5)
# ---------------------------------------------------------------------------


def _agregar_raiz_repo_a_syspath():
    """Inserta la raiz del repo en sys.path (shim D5).

    Los scripts corren con sys.path[0] = su propio directorio
    (``python3 render_distribuido/render_config.py``) y SamanTools no es
    importable sin la raiz del repo en el path.
    """
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if raiz not in sys.path:
        sys.path.insert(0, raiz)


def _cargar_entorno():
    """Importa ``SamanTools.entorno`` lazy, con shim de sys.path (D5)."""
    global _entorno_mod
    if _entorno_mod is not None:
        return _entorno_mod
    try:
        from SamanTools import entorno as mod
    except (ImportError, AttributeError):
        _agregar_raiz_repo_a_syspath()
        try:
            from SamanTools import entorno as mod
        except (ImportError, AttributeError):
            mod = None
    _entorno_mod = mod
    return mod


def _resolver_base():
    """Devuelve (base, origen) con origen 'env' | 'entorno'.

    ``RENDER_CONFIG_BASE`` gana a ``entorno.primera_ruta_disponible()`` y
    salta el gate de montaje (D4: la base por env es intencion del admin).
    (None, None) si no hay base.
    """
    base_env = os.environ.get(ENV_BASE)
    if base_env:
        return base_env, "env"
    mod = _cargar_entorno()
    if mod is None:
        return None, None
    base = mod.primera_ruta_disponible(mod.detectar_so())
    if not base:
        return None, None
    return base, "entorno"


# ---------------------------------------------------------------------------
# Gate de montaje (D7)
# ---------------------------------------------------------------------------


def _gate_mount(base, timeout=3, intentos=2):
    """Gate de montaje cache-free (D7): verifica que {base} responda.

    Presupuesto 2 x 3s (6s) una vez por corrida. Reintenta con SU propio
    ``ls -d`` (``dir`` en Windows) y timeout local; NO usa
    ``entorno.estado_unidad`` porque su cache de 10s hace no-op el reintento
    (gotcha verificado en entorno.py). True si un intento responde; False si
    todos fallan => montaje caido (error de montaje, no "config missing").
    """
    if os.name == "nt":
        cmd = ["cmd", "/c", "dir", base]
    else:
        cmd = ["ls", "-d", base]
    for _ in range(max(1, intentos)):
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            continue  # mount colgado (el kernel intenta reconectar): reintentar
        except (FileNotFoundError, OSError):
            if os.path.isdir(base):
                return True  # comando ausente, pero la base responde
            continue
        if proc.returncode == 0:
            return True
    return False


# ---------------------------------------------------------------------------
# Lectura del disco y del override local
# ---------------------------------------------------------------------------


def _leer_json_disco(ruta):
    """Lee y parsea {ruta}; lanza _ErrorDisco con el tipo de fallo."""
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            datos = json.load(f)
    except FileNotFoundError:
        raise _ErrorDisco("faltante", ruta=ruta, detalle="archivo ausente")
    except (OSError, TimeoutError) as e:  # incluye EIO: mount LucidLink roto
        raise _ErrorDisco("montaje", ruta=ruta, detalle=str(e))
    except ValueError:  # json.JSONDecodeError
        raise _ErrorDisco("invalido", ruta=ruta, detalle="JSON corrupto")
    if not isinstance(datos, dict):
        raise _ErrorDisco(
            "invalido", ruta=ruta, detalle="no es un dict (%s)" % type(datos).__name__
        )
    return datos


def _cargar_config_local():
    """Devuelve ``RENDER_LOCAL_CONFIG`` (dict) de config_local.py, o None.

    config_local.py es gitignored (override local por-maquina). Se busca en
    ``SamanTools.config_local`` (patron vfxflow), ``render_distribuido.
    config_local`` y ``config_local`` (script mode). Un dict ausente o no
    dict se ignora: None.
    """
    for nombre in (
        "SamanTools.config_local",
        "render_distribuido.config_local",
        "config_local",
    ):
        try:
            modulo = importlib.import_module(nombre)
        except (ImportError, AttributeError):
            continue
        local = getattr(modulo, "RENDER_LOCAL_CONFIG", None)
        if isinstance(local, dict):
            return local
    return None


# ---------------------------------------------------------------------------
# Validador de esquema (unico, puro)
# ---------------------------------------------------------------------------


def _guia(llave):
    """Guia de arreglo corta por llave obligatoria."""
    guias = {
        "bases_por_so": "dict {SO: ruta}, ej. {'macOS': '/Volumes/wupm/2026'}",
        "workers": "lista de dicts de worker",
        "sufijos": "dict {TO_VFX, COMP, FROM_VFX} con los sufijos del estudio",
        "TO_VFX": "sufijo del subdirectorio TO_VFX, ej. '/HTLR/TO_VFX/'",
        "COMP": "sufijo del subdirectorio COMP, ej. '/HTLR/COMP/'",
        "FROM_VFX": "sufijo del subdirectorio FROM_VFX, ej. '/HTLR/FROM_VFX/'",
        "nombre": "nombre del worker",
        "ssh": "host SSH del worker, o None si es la maquina local",
        "ssh_user": "usuario SSH del worker",
        "nuke_exec": "ruta absoluta del binario de Nuke en el worker",
        "base": "base declarada del worker bajo bases_por_so",
        "lc_all": "bool: prefijar LC_ALL=C en el comando remoto",
    }
    return guias.get(llave, "valor valido segun el esquema")


def _error_falta(path, llave):
    return "%s: falta la llave obligatoria (%s)." % (path, _guia(llave))


def _error_tipo(path, esperado, encontrado):
    return (
        "%s: tipo incorrecto: se esperaba %s, se encontro %s."
        % (path, esperado, type(encontrado).__name__)
    )


def validar_esquema(config):
    """Valida el esquema por niveles y acumula TODOS los errores (puro).

    Devuelve [] si la config es valida; si no, una lista de strings con key
    path (ej. ``workers[1].nuke_exec``), tipo esperado/encontrado y guia de
    arreglo. Es el MISMO validador para la fusion disco+local, para la
    autonomia del local solo, y para validar un dict cualquiera (ej.
    studio_config.example.json).

    TODO(T2/PR2): integridad D2 - worker.base debe caer bajo una base
    declarada de bases_por_so (usa _canon de T2).
    """
    if not isinstance(config, dict):
        return [
            "config: tipo incorrecto: se esperaba dict, se encontro %s."
            % type(config).__name__
        ]

    errores = []

    # --- primer nivel: presencia + tipo ---
    for llave in LLAVES_PRIMER_NIVEL:
        if llave not in config:
            errores.append(_error_falta(llave, llave))
    if "bases_por_so" in config and not isinstance(config["bases_por_so"], dict):
        errores.append(_error_tipo("bases_por_so", "dict", config["bases_por_so"]))
    if "workers" in config and not isinstance(config["workers"], list):
        errores.append(_error_tipo("workers", "list", config["workers"]))
    if "sufijos" in config and not isinstance(config["sufijos"], dict):
        errores.append(_error_tipo("sufijos", "dict", config["sufijos"]))

    # --- bases_por_so: valores string ---
    bases = config.get("bases_por_so")
    if isinstance(bases, dict):
        for so, ruta in bases.items():
            if not isinstance(ruta, str):
                errores.append(
                    _error_tipo("bases_por_so[%r]" % so, "str (ruta)", ruta)
                )

    # --- sufijos: TO_VFX/COMP/FROM_VFX presentes y string ---
    sufijos = config.get("sufijos")
    if isinstance(sufijos, dict):
        for sub in LLAVES_SUFIJOS:
            path = "sufijos.%s" % sub
            if sub not in sufijos:
                errores.append(_error_falta(path, sub))
            elif not isinstance(sufijos[sub], str):
                errores.append(_error_tipo(path, "str", sufijos[sub]))

    # --- workers: lista de dicts, cada uno con las 6 llaves y tipos ---
    workers = config.get("workers")
    if isinstance(workers, list):
        for i, worker in enumerate(workers):
            prefijo = "workers[%d]" % i
            if not isinstance(worker, dict):
                errores.append(_error_tipo(prefijo, "dict", worker))
                continue
            for llave in LLAVES_WORKER:
                path = "%s.%s" % (prefijo, llave)
                if llave not in worker:
                    errores.append(_error_falta(path, llave))
                    continue
                valor = worker[llave]
                if llave in ("nombre", "ssh_user", "nuke_exec", "base"):
                    if not isinstance(valor, str):
                        errores.append(_error_tipo(path, "str", valor))
                elif llave == "ssh":
                    if valor is not None and not isinstance(valor, str):
                        errores.append(
                            _error_tipo(path, "str o None", valor)
                        )
                elif llave == "lc_all":
                    if not isinstance(valor, bool):
                        errores.append(_error_tipo(path, "bool", valor))

    return errores


# ---------------------------------------------------------------------------
# Fusion y politica estricta
# ---------------------------------------------------------------------------


def _merge_config(disco, local):
    """Merge per-key (D3): local sobreescribe al JSON por llave de 1er nivel.

    Si ambos valores son dicts se fusionan por item (un nivel), para que el
    local pueda sobreescribir una sola entrada (ej. la base Linux) sin
    repetir el dict completo; si no, el valor del local reemplaza (ej. la
    lista completa de workers).
    """
    if not local:
        return disco
    resultado = dict(disco or {})
    for llave, valor_local in local.items():
        valor_disco = resultado.get(llave)
        if isinstance(valor_disco, dict) and isinstance(valor_local, dict):
            fusion = dict(valor_disco)
            fusion.update(valor_local)
            resultado[llave] = fusion
        else:
            resultado[llave] = valor_local
    return resultado


def _contexto_disco(error_disco):
    """Frase corta de contexto sobre por que el disco no dio config."""
    if error_disco is None:
        return "sin config en disco"
    if error_disco.tipo == "montaje":
        return "fallo de conexion o montaje (%s)" % error_disco.detalle
    if error_disco.tipo == "invalido":
        return "JSON invalido (%s)" % error_disco.detalle
    if error_disco.tipo == "sin_base":
        return "sin base disponible"
    return "archivo ausente"


def _abortar_esquema(errores):
    """SystemExit con TODAS las faltantes/tipos y como arreglarlas."""
    detalle = "\n".join("  - %s" % e for e in errores)
    raise SystemExit(
        "Config de render invalida: %d error(es) de esquema.\n%s"
        % (len(errores), detalle)
    )


def _abortar_local_incompleto(error_disco, errores):
    """Local incompleto sin disco: diagnostico de llaves faltantes."""
    detalle = "\n".join("  - %s" % e for e in errores)
    raise SystemExit(
        "No hay config completa en disco (%s) y el override local "
        "RENDER_LOCAL_CONFIG tampoco cumple el esquema:\n%s"
        % (_contexto_disco(error_disco), detalle)
    )


def _abortar_sin_fuente(error_disco):
    """Sin disco ni local: politica estricta diferenciada por tipo de fallo."""
    if error_disco.tipo == "montaje":
        raise SystemExit(
            "Fallo de conexión o montaje: no se pudo acceder a %s (%s). "
            "Verifica que la unidad LucidLink wupm esté montada y con red, y "
            "reintenta cuando el mount responda."
            % (error_disco.ruta or "{base}/" + ARCHIVO_DISCO, error_disco.detalle)
        )
    if error_disco.tipo == "invalido":
        ruta = error_disco.ruta or "{base}/" + ARCHIVO_DISCO
        raise SystemExit(
            "Config de render inválida: %s no es un JSON válido ni un dict "
            "(%s). Copia render_distribuido/%s a %s y recrea la config del "
            "estudio." % (ruta, error_disco.detalle, ARCHIVO_EJEMPLO, ruta)
        )
    if error_disco.tipo == "sin_base":
        raise SystemExit(
            "Config de render faltante: no hay base disponible (unidad wupm "
            "no montada ni %s definida). Copia render_distribuido/%s a "
            "{base}/%s y completa la config del estudio."
            % (ENV_BASE, ARCHIVO_EJEMPLO, ARCHIVO_DISCO)
        )
    # faltante (FileNotFoundError o archivo ausente tras el gate)
    ruta = error_disco.ruta or "{base}/" + ARCHIVO_DISCO
    raise SystemExit(
        "Config de render faltante: no se encontró %s. Copia "
        "render_distribuido/%s a %s y completa workers, bases y sufijos "
        "del estudio." % (ruta, ARCHIVO_EJEMPLO, ruta)
    )


def obtener_config_efectiva():
    """Config efectiva estricta: base -> JSON del disco -> merge local.

    Cadena:
        1. Resuelve la base (env gana; si no, entorno con shim D5).
        2. Gate de montaje si la base viene de entorno (D4/D7); lee el JSON.
        3. Merge per-key con RENDER_LOCAL_CONFIG (D3).
        4. Valida el esquema; aborta con TODAS las faltantes si es invalido.

    Politica estricta (spec: Strict availability policy): sin base, archivo
    faltante o JSON invalido y sin local completo => SystemExit sugiriendo
    copiar studio_config.example.json. OSError/TimeoutError/EIO o gate caido
    => SystemExit con fallo de conexion/montaje, sin sugerir la plantilla.
    Autonomia (spec: Local complete, no disk): un RENDER_LOCAL_CONFIG
    completo rescata la ausencia/fallo del disco sin abort.
    """
    base, origen = _resolver_base()

    disco = None
    error_disco = None
    ruta_disco = None
    if base:
        ruta_disco = os.path.join(base, *ARCHIVO_DISCO.split("/"))
        if origen == "entorno" and not _gate_mount(base):
            error_disco = _ErrorDisco(
                "montaje",
                ruta=ruta_disco,
                detalle="gate de montaje: todos los intentos fallaron",
            )
        if error_disco is None:
            try:
                disco = _leer_json_disco(ruta_disco)
            except _ErrorDisco as e:
                error_disco = e
    else:
        error_disco = _ErrorDisco("sin_base")

    local = _cargar_config_local()

    if disco is not None:
        config = _merge_config(disco, local)
        errores = validar_esquema(config)
        if errores:
            _abortar_esquema(errores)
        return config

    # Disco no disponible: el local completo rescata (autonomia).
    if local is not None:
        errores = validar_esquema(local)
        if errores:
            _abortar_local_incompleto(error_disco, errores)
        return local

    _abortar_sin_fuente(error_disco)