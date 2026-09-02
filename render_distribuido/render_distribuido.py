#!/usr/bin/env python3
"""Distribuye un render entre varias maquinas (macOS/Linux) con reparto inteligente.

Fase PROBE: detecta el rango del Read del PLATE (frames del proyecto) y el
  patron de salida del Write de entrega, sin renderizar.

Fase EXISTENTES: revisa que frames ya estan exportados en el destino y valida
  los EXR (header magico + tamano; validacion profunda opcional con Nuke).

Fase POLITICA: si hay frames existentes pregunta UNA VEZ al usuario si
  reemplazarlos. Default NO (se renderiza solo lo faltante: no se pierde
  trabajo). Opciones: No / Si / Solo corruptos.

Fase CALIB (estratificada sobre los frames a renderizar) + PLAN (coste fijo +
  variable) + RENDER distribuido en paralelo. Reporte planificado vs real.

La infraestructura (workers, bases por SO y sufijos por defecto) NO vive en el
codigo: se resuelve desde la config central estricta
``render_config.obtener_config_efectiva()`` (ver render_config.py). El CLI
solo puede sobreescribir los sufijos por corrida.

Uso:
  python3 render_distribuido.py --comp ..._comp_SAMAN_V05.nk \
      --wnode DELIVERY_EXR --auto-range \
      [--to-suf SUF] [--comp-suf SUF] [--from-suf SUF] \
      [--politica ask|keep|replace|corruptos] [--check-exr]
"""

import argparse
import concurrent.futures
import json
import os
import platform
import re
import struct
import subprocess
import sys
import time

try:
    from render_distribuido import render_config
except ImportError:  # script mode: sys.path[0] es la carpeta render_distribuido
    import render_config

try:
    from render_distribuido import layouts
except ImportError:  # script mode
    import layouts


def ruta_repo(worker):
    return worker["base"] + "/saman-nuke-tools/render_distribuido"


def construir_workers(config_workers):
    """Convierte los workers de la config central a la forma interna.

    ``ssh`` se compone como ``ssh_user + "@" + host`` SOLO cuando el worker es
    remoto (``ssh`` no nulo/vacio); local queda ``None``. ``bin`` pasa a ser
    ``nuke_exec`` de la config; ``base`` y ``lc_all`` se copian tal cual.

    Defensa: si el host ya viene con el usuario incluido (configs escritas
    a mano), no duplicamos el usuario: se usa el host tal cual.
    """
    workers = []
    for w in config_workers:
        host = w["ssh"]
        if host and "@" not in host:
            host = "%s@%s" % (w["ssh_user"], host)
        workers.append(
            {
                "nombre": w["nombre"],
                "ssh": host,
                "bin": w["nuke_exec"],
                "base": w["base"],
                "lc_all": w["lc_all"],
            }
        )
    return workers


def filtrar_por_nombre(workers, nombres_csv):
    """Filtra los workers por nombre (--workers); None/vacio => todos.

    Los nombres se comparan en Python y jamas llegan a un shell.
    """
    if not nombres_csv:
        return workers
    nombres = [w.strip() for w in nombres_csv.split(",") if w.strip()]
    return [w for w in workers if w["nombre"] in nombres]


# ---------------------------------------------------------------------------
# Multi-nodo (PR2, D4): nombres REALES de Write del comp (RC-MN-01)
# ---------------------------------------------------------------------------

# Los roles semanticos fijos (entrega/preview) se mapean exclusivamente a los
# nombres reales de los Write del comp. Los labels friendly ("delivery",
# "preview", "side by side") NUNCA son nombres de nodo (RC-MN-01).
NODOS_ENTREGA = ("DELIVERY_EXR", "DELIVERY_DWG")
NODOS_PREVIEW = ("REVIEW_REC709", "SBS_REC709")
NODOS_RENDER = NODOS_ENTREGA + NODOS_PREVIEW


def filtrar_wnodes(descubiertos, wnodes_arg=None):
    """Filtra los nodos descubiertos de la PROBE (RC-MN-01).

    ``--wnodes`` explicito: solo los nombrados que fueron descubiertos (los
    nombres se comparan en Python y jamas llegan a un shell). Sin ``--wnodes``:
    todos los descubiertos con rol de entrega (DELIVERY_*); los previews
    piggyback en el batch del delivery (D4).
    """
    if wnodes_arg:
        pedidos = [n.strip() for n in wnodes_arg.split(",") if n.strip()]
        return [n for n in descubiertos if n in pedidos]
    return [n for n in descubiertos if n in NODOS_ENTREGA]


def sufijos_efectivos(sufijos_config, to_suf=None, comp_suf=None, from_suf=None):
    """Sufijos efectivos de la corrida: lo que de el CLI (si viene), si no config.

    Cumple el escenario "Suffix defaults from config": correr sin --to-suf usa
    ``sufijos_config["TO_VFX"]``; el CLI puede sobreescribir por corrida.
    """
    return {
        "TO_SUF": to_suf if to_suf is not None else sufijos_config["TO_VFX"],
        "COMP_SUF": comp_suf if comp_suf is not None else sufijos_config["COMP"],
        "FROM_SUF": from_suf if from_suf is not None else sufijos_config["FROM_VFX"],
    }


def so_local():
    """SO de la maquina del ORQUESTADOR con la clave del esquema de la config."""
    sistema = platform.system()
    return {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}.get(
        sistema, sistema
    )


def ejecutar(worker, argv, env=None, timeout=600):
    cmd = []
    if worker["ssh"]:
        cmd = [
            "ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
            worker["ssh"],
        ]
        lista_env = " ".join("%s='%s'" % (k, v) for k, v in (env or {}).items())
        extra = "LC_ALL=C " if worker["lc_all"] else ""
        cmd.append("env %s%s %s" % (extra, lista_env, " ".join(argv)))
    else:
        cmd = argv
    e = dict(os.environ)
    if env:
        e.update(env)
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=e)
    return p.returncode, p.stdout + p.stderr


def parsear_worker_out(salida):
    for linea in reversed(salida.splitlines()):
        if "__WORKER__" in linea:
            try:
                idx = linea.index("__WORKER__")
                return json.loads(linea[idx + len("__WORKER__"):])
            except Exception:
                return None
    return None


def medir(worker, argv, env=None, timeout=600):
    t0 = time.time()
    rc, salida = ejecutar(worker, argv, env, timeout=timeout)
    dur = time.time() - t0
    return dur, rc, salida


def env_worker(worker, args, mode):
    base_env = {
        "MODE": mode,
        "BASE": worker["base"],
        "COMP": worker["base"] + "/" + args.comp,
        "WNODE": args.wnode,
        "TO_SUF": args.to_suf,
        "COMP_SUF": args.comp_suf,
        "FROM_SUF": args.from_suf,
    }
    if getattr(args, "wnodes", None):
        # Nombres YA filtrados en Python contra el discovery (RC-MN-01).
        base_env["WNODES"] = args.wnodes
    if getattr(args, "piggyback", None) and mode == "render":
        base_env["PIGGYBACK"] = args.piggyback
    if getattr(args, "force_exr", False) and mode == "render":
        base_env["FORCE_EXR"] = "1"
    return base_env


def probar(worker, args):
    pu = ruta_repo(worker)
    dur, rc, sal = medir(
        worker,
        [worker["bin"], "-t", pu + "/render_worker.py"],
        env_worker(worker, args, "probe"),
    )
    return parsear_worker_out(sal) or {}


def calibrar(worker, args, frames_diana):
    pu = ruta_repo(worker)
    startup_s, rc, _ = medir(worker, [worker["bin"], "-t", pu + "/hello.py"])
    env = env_worker(worker, args, "calib")
    # La calibracion NUNCA escribe al destino real: usa una carpeta por worker
    # (los N frames de muestra en paralelo colisionarian en el storage).
    env["FROM_SUF"] = "/TEST_RENDER/calib_" + worker["nombre"] + "/"
    env["CALIB_FRAMES"] = str(min(args.calib, max(1, len(frames_diana))))
    if args.strat and frames_diana:
        muestra = [
            frames_diana[int((len(frames_diana) - 1) * i / max(1, args.calib - 1))]
            for i in range(min(args.calib, len(frames_diana)))
        ]
        env["CALIB_LIST"] = ",".join(str(int(x)) for x in muestra)
    dat = None
    try:
        dur, rcc, sal = medir(
            worker,
            [worker["bin"], "-t", pu + "/render_worker.py"],
            env,
        )
        dat = parsear_worker_out(sal)
        if dat is None:
            dat = {"error": "sin parsear", "rc": rcc, "tail": sal.splitlines()[-6:]}
    except Exception as e:
        dat = {"error": str(e)}
    return {
        "worker": worker["nombre"],
        "startup_s": round(startup_s, 3),
        "calib": dat or {"error": "sin parsear"},
    }


def repartir(F, costes):
    mejor_t = None
    mejor_ns = None
    m = len(costes)

    def iterar(ns, idx, restante):
        nonlocal mejor_t, mejor_ns
        if idx == m - 1:
            ns = ns + [restante]
            t = max(
                (a + b * n) for (a, b), n in zip(costes, ns) if n > 0
            ) if restante >= 0 else None
            if restante >= 0 and (mejor_t is None or t < mejor_t):
                mejor_t = t
                mejor_ns = list(ns)
            return
        for n in range(restante + 1):
            iterar(ns + [n], idx + 1, restante - n)

    iterar([], 0, F)
    return mejor_t, mejor_ns


def rendir(worker, args, lista_frames):
    pu = ruta_repo(worker)
    env = env_worker(worker, args, "render")
    env["RENDER_LIST"] = ",".join(str(int(x)) for x in lista_frames)
    dur, rc, sal = medir(
        worker,
        [worker["bin"], "-t", pu + "/render_worker.py"],
        env,
    )
    dat = parsear_worker_out(sal)
    return {
        "worker": worker["nombre"],
        "frames": len(lista_frames),
        "real_s": round(dur, 3),
        "render_s": (dat or {}).get("render_s"),
        "rc": rc,
    }


def rendir_archivo(worker, args, nodo, primero, ultimo):
    """Render de un archivo UNICO (MOV): nuke.execute(nodo, primero, ultimo).

    Sin reparto: el archivo se escribe entero en una invocacion (RC-MN-02).
    Los previews NO piggyback aca (ya viajaron con el batch EXR del delivery).
    """
    pu = ruta_repo(worker)
    env = env_worker(worker, args, "render")
    env["WNODE"] = nodo
    env["FIRST"] = str(primero)
    env["LAST"] = str(ultimo)
    env.pop("RENDER_LIST", None)
    env.pop("PIGGYBACK", None)
    dur, rc, sal = medir(
        worker,
        [worker["bin"], "-t", pu + "/render_worker.py"],
        env,
    )
    dat = parsear_worker_out(sal)
    return {
        "worker": worker["nombre"],
        "archivo": nodo,
        "real_s": round(dur, 3),
        "render_s": (dat or {}).get("render_s"),
        "rc": rc,
    }


# ---------------------------------------------------------------------------
# Frames existentes / validacion / politica de reemplazo
# ---------------------------------------------------------------------------

PAD_EXPR = re.compile(r"#+|\%0\d+d")
TEMPLATE_EXPR = re.compile(r"(\d{4})(?=\.exr$)")


def tipo_salida(template):
    """'sequence' (EXR por frame) | 'archivo' (MOV single-file) (RC-MN-02).

    Un placeholder de frame (``####``/``%0Nd``) o digitos justo antes de
    ``.exr`` => sequence. Un ``.mov`` — aunque tenga digitos en el nombre —
    es archivo unico (threat 'Output existence classification': jamas
    clasificar un .mov con digitos como secuencia EXR).
    """
    if not template:
        return None
    if PAD_EXPR.search(template) or TEMPLATE_EXPR.search(template):
        return "sequence"
    return "archivo"


def derivar_template(sample):
    """Convertir un file evaluado en plantilla de frames (multi-nodo, D4).

    - placeholder ya presente (``####``/``%0Nd``) => intacto;
    - EXR con digitos antes de ``.exr`` => ``####.exr`` (secuencia);
    - single-file (``.mov`` u otro, aun con digitos) => literal, sin
      placeholder (RC-MN-02: la politica MOV es por archivo).
    """
    if not sample:
        return None
    if PAD_EXPR.search(sample):
        return sample
    if TEMPLATE_EXPR.search(sample):
        return TEMPLATE_EXPR.sub("####", sample, count=1)
    return sample


def template_local(template, config):
    """Traduce el template a la base montada en la maquina del ORQUESTADOR.

    El worker que reporta el template puede usar otra base declarada en
    ``bases_por_so`` (Linux, Windows) mientras el orquestador monta la suya
    (ej. macOS). La traduccion usa ``render_config.traducir_ruta`` sobre el
    mapa de bases de la config (multi-SO, generaliza el par /mnt<->/Volumes).
    Template fuera de prefijos declarados o sin traduccion => intacto
    (spec: Unknown prefix)."""
    if not template:
        return template
    desde = render_config.detectar_so_de_ruta(template, config)
    if desde is None:
        return template
    return render_config.traducir_ruta(template, desde, so_local(), config)


def path_frame(template, n):
    def _rep(m):
        frag = m.group(0)
        if frag.startswith("%"):
            return str(n).zfill(int(frag[2:-1]))
        return str(n).zfill(len(frag))
    return PAD_EXPR.sub(_rep, template)


def header_exr_valido(path):
    """Check barato pero ESTRUCTURAL del EXR (sin decodificar scanlines).

    Valida: magic 'v/1\\1', cabecera parseable (dataWindow + compression),
    tabla de offsets de chunks completa y coherente, y el chunk leader del
    primer chunk. Detecta el patron real de corrupcion LucidLink/FUSE:
    tamano normal pero tabla de offsets rota / chunk leader invalido.
    """
    try:
        if not os.path.isfile(path):
            return False
        size = os.path.getsize(path)
        if size < 1024:
            return False
        with open(path, "rb") as f:
            if f.read(4) != b"v/1\x01":
                return False
            ver = f.read(4)
            tiled = bool(struct.unpack("<I", ver)[0] & 0x00000200)
            # cabecera: atributos null-terminated (nombre, tipo), size, valor
            compression = None
            dw = None
            while True:
                nombre = b""
                while True:
                    c = f.read(1)
                    if not c:
                        return False
                    if c == b"\x00":
                        break
                    nombre += c
                if nombre == b"":
                    break  # fin de cabecera (atributo vacio/terminador)
                while True:
                    c = f.read(1)
                    if not c:
                        return False
                    if c == b"\x00":
                        break
                sz = struct.unpack("<I", f.read(4))[0]
                val = f.read(sz)
                if len(val) != sz:
                    return False
                if nombre == b"dataWindow":
                    dw = struct.unpack("<iiii", val)
                elif nombre == b"compression":
                    compression = val[0]
            if dw is None or compression is None:
                return False
            if tiled:
                return True  # tiled: estructura distinta; no evaluamos aqui
            mny, mxy = dw[1], dw[3]
            height = mxy - mny + 1
            lines_bloque = {0: 1, 1: 1, 2: 1, 3: 16, 4: 32, 5: 16,
                            6: 32, 7: 32, 8: 32, 9: 256}.get(compression, 16)
            nchunks = (height + lines_bloque - 1) // lines_bloque
            off = f.tell()
            if off + nchunks * 8 > size:
                return False
            f.seek(off)
            tabla = struct.unpack("<%dQ" % nchunks, f.read(nchunks * 8))
            first = tabla[0]
            if first == 0 or first < off + nchunks * 8:
                return False
            prev = first
            for i, v in enumerate(tabla[1:], 1):
                if v == 0 or v < prev:
                    return False
                prev = v
            if tabla[-1] + 8 > size:
                return False
            # chunk leader del primer chunk: y == dataWindow.min.y
            f.seek(first)
            leader = f.read(8)
            if len(leader) < 8:
                return False
            y, dsz = struct.unpack("<ii", leader)
            if y != mny or dsz <= 0 or first + 8 + dsz > size:
                return False
        return True
    except (OSError, struct.error, EOFError):
        return False


def frames_existentes(template, inicio, fin):
    por_frame = []
    for n in range(inicio, fin + 1):
        p = path_frame(template, n)
        if os.path.isfile(p):
            por_frame.append((n, p))
    return por_frame


# ---------------------------------------------------------------------------
# Multi-nodo (PR2, D4): politica por nodo (EXR por frame / MOV por archivo),
# CALIB/PLAN solo entrega EXR, previews piggyback y --force-exr (RC-MN-02/03)
# ---------------------------------------------------------------------------


def archivo_existente(path):
    """Existencia de un archivo UNICO (MOV): os.path.isfile (RC-MN-02)."""
    return bool(path) and os.path.isfile(path)


def decidir_frames_por_politica(politica, rango, existentes_n, corruptos):
    """Frames a renderizar segun la politica, desacoplada de args (multi-nodo).

    - replace: todo el rango.
    - corruptos: solo los corruptos validados.
    - keep (default): no pierde trabajo valido => faltantes + corruptos.
    """
    if politica == "replace":
        return sorted(rango)
    if politica == "corruptos":
        return sorted(set(corruptos))
    validos = set(existentes_n) - set(corruptos)
    return sorted(set(rango) - validos)


def rango_efectivo_nodo(info, inicio, fin):
    """Rango efectivo de render/existencia de un nodo (RC-MN-02, use_limit).

    Con ``use_limit`` activo el Write confina su propio first/last; sin el
    knob, el nodo cubre el rango de la corrida [inicio..fin].
    """
    if (info and info.get("use_limit")
            and info.get("first") is not None and info.get("last") is not None):
        return int(info["first"]), int(info["last"])
    return inicio, fin


def plan_nodo(info, template, inicio, fin, politica="keep"):
    """Plan de existencia/render para UN nodo (RC-MN-02).

    sequence EXR: {tipo, existentes:[(n,path)], corruptos:[n], decision,
    a_render:[frames]}. archivo MOV: {tipo, existe, decision: skip|render,
    a_render: [] | [path]} — un archivo se renderiza entero o se salta.
    """
    tipo = tipo_salida(template)
    if tipo == "sequence":
        existentes = frames_existentes(template, inicio, fin)
        corruptos = [n for n, p in existentes if not header_exr_valido(p)]
        a_render = decidir_frames_por_politica(
            politica, range(inicio, fin + 1), [n for n, _ in existentes], corruptos
        )
        decision = "skip" if not a_render else politica
        return {
            "tipo": tipo,
            "existentes": existentes,
            "corruptos": corruptos,
            "decision": decision,
            "a_render": a_render,
        }
    existe = archivo_existente(template)
    if existe and politica in ("keep", "ask", "corruptos"):
        return {"tipo": tipo, "existe": True, "decision": "skip", "a_render": []}
    return {"tipo": tipo, "existe": existe, "decision": "render", "a_render": [template]}


def exigir_delivery_exr(en_scope):
    """CALIB/PLAN solo sobre DELIVERY_EXR (RC-MN-02).

    Si el filtro ``--wnodes`` lo excluye o el comp no lo tiene => abort claro,
    sin degradacion silenciosa.
    """
    if "DELIVERY_EXR" not in en_scope:
        raise SystemExit(
            "CALIBRACION/PLAN requieren el nodo DELIVERY_EXR; nodos en "
            "alcance: %s" % (", ".join(en_scope) or "ninguno")
        )


def env_piggyback(descubiertos, en_scope, inicio, fin):
    """Env PIGGYBACK 'NAME:first:last,...' de previews (D4, RC-MN-02).

    Cada preview descubierto que NO este ya en alcance viaja en el mismo
    batch del delivery con SU rango efectivo (use_limit => first/last reales;
    si no, el rango de la corrida). None si no hay previews.
    """
    partes = []
    for nombre in descubiertos:
        if nombre not in NODOS_PREVIEW or nombre in en_scope:
            continue
        e_i, e_f = rango_efectivo_nodo(descubiertos[nombre], inicio, fin)
        partes.append("%s:%d:%d" % (nombre, e_i, e_f))
    return ",".join(partes) or None


def forzar_template_exr(file):
    """--force-exr: plantilla de secuencia EXR para el nodo de entrega (RC-MN-03).

    Archivo unico (mov/etc.) => mismo dir/base con ``####.exr``: la duracion
    (rango) y la resolucion (formato del Write) no se tocan. Ya secuencia EXR
    => derivar_template normal.
    """
    if not file:
        return None
    if tipo_salida(file) == "sequence":
        return derivar_template(file)
    return os.path.splitext(file)[0] + ".####.exr"


def politica_reemplazo(args, existentes, corruptos):
    """Decide que frames renderizar dados los existentes.

    - ask (default): pregunta una vez al usuario [n/s/c].
    - keep: nunca reemplaza (solo faltantes + corruptos? no: sin reemplazar).
    - replace: re-renderiza todo el rango.
    - corruptos: re-renderiza solo faltantes + corruptos validados.
    """
    validos = [n for n, _ in existentes if n not in corruptos]
    a_render = []
    decision = args.politica
    if existentes and args.politica == "ask":
        print("\n== EXISTENTES ==")
        print("  %d frames ya exportados en el destino (%d sospechosos/corruptos)."
              % (len(existentes), len(corruptos)))
        try:
            resp = input("  ¿Reemplazarlos? [n]o / [s]i / [c]orruptos (default no): ").strip().lower()
        except EOFError:
            resp = "n"
        if resp in ("s", "si", "y", "yes"):
            decision = "replace"
        elif resp in ("c", "corruptos"):
            decision = "corruptos"
        else:
            decision = "keep"
    if decision == "replace":
        a_render = list(range(args.start, args.start + args.frames))
    elif decision == "corruptos":
        a_render = sorted(set(corruptos))
    else:  # keep: no pierde trabajo valido; renderiza faltantes + reparar corruptos
        rango = set(range(args.start, args.start + args.frames))
        existentes_n = {n for n, _ in existentes}
        validos = existentes_n - corruptos
        a_render = sorted(rango - validos)
    return decision, a_render


def check_profundo(worker, args, paths):
    """Valida EXR con Nuke (Read + execute). Devuelve set de frames corruptos."""
    pu = ruta_repo(worker)
    env = env_worker(worker, args, "check")
    env["CHECK_LIST"] = ",".join(paths)
    dur, rc, sal = medir(worker, [worker["bin"], "-t", pu + "/render_worker.py"], env)
    dat = parsear_worker_out(sal) or {}
    res = dat.get("check") or {}
    corruptos = set()
    for p, estado in res.items():
        if not estado.startswith("ok"):
            try:
                corruptos.add(int(path_frame(p, 1).split(".")[-2] if False else int(re.search(r"(\d+)\.exr$", p).group(1))))
            except Exception:
                pass
    return corruptos


# ---------------------------------------------------------------------------
# Flujo asistido: layout + seleccion por mtime (PR1, D1/D2)
# ---------------------------------------------------------------------------


def resolver_proyecto(proyecto_arg):
    """(proyecto, aviso): default HTLR con aviso explicito (RC-SS-03).

    Sin ``--proyecto`` el flujo asistido usa HTLR y lo anuncia; con el flag
    explicito no hay aviso.
    """
    if proyecto_arg:
        return proyecto_arg, False
    print("AVISO: proyecto no especificado; se usa HTLR (default).")
    return "HTLR", True


def es_flujo_asistido(args):
    """True si la corrida usa flags nuevos del flujo asistido.

    Legacy (solo ``--comp`` y flags viejos) => False: sin seleccion por
    layout ni gate, para no regresionar (RC-QC-04).
    """
    return bool(
        args.proyecto or args.comp_dir or args.resolve_latest or args.use_version
    )


def planos_del_proyecto(args, config):
    """Carpetas de planos (relativas a la base) del flujo asistido.

    ``--comp-dir`` con carpeta literal existente => se usa tal cual (carpeta
    unica directa, RC-SS-03). Si el valor NO existe literalmente bajo la
    base, se trata como intencion y se remapea con el layout del proyecto
    (RC-SS-01: ``2VFX/Capitulo_7`` -> ``EP_07``). Sin ``--comp-dir`` =>
    abort claro (nunca skip silencioso).
    """
    if not args.comp_dir:
        raise SystemExit(
            "Flujo asistido: falta --comp-dir (carpeta de planos relativa a "
            "la base, ej. HTLR/COMP/EP_07/<plan>, o una intencion como "
            "'Capitulo 7')."
        )
    ruta_abs = layouts.ruta_bajo_base(args.comp_dir, config)
    if ruta_abs and os.path.isdir(ruta_abs):
        return [args.comp_dir]
    # Default HTLR cuando el CLI no trajo --proyecto (misma regla que main).
    return layouts.resolver_planos(args.comp_dir, args.proyecto or "HTLR", config)


def confirmar_planos(planos, args, leer=None, imprimir=None):
    """Confirma la seleccion: [Confirmar] / [Ver lista y desmarcar] (RC-SS-03).

    ``--resolve-latest``: confirma todo SIN prompt. Sin TTY (EOFError):
    confirma todo. ``lista``/``desmarcar``: muestra la lista numerada y deja
    desmarcar por indice en una ronda => subset confirmado para render.
    """
    if args.resolve_latest:
        return list(planos)
    if leer is None:
        leer = input
    if imprimir is None:
        imprimir = print
    imprimir("\n== SELECCION ==")
    imprimir(
        "  %d planos detectados. [Confirmar] / [Ver lista y desmarcar]"
        % len(planos)
    )
    try:
        respuesta = leer("  Accion (default confirmar): ").strip().lower()
    except EOFError:
        return list(planos)
    lista = ("lista", "desmarcar", "ver", "l", "d")
    if respuesta in lista:
        imprimir("  Lista de planos:")
        for i, p in enumerate(planos, 1):
            imprimir("    %2d) %s" % (i, p))
        try:
            excl = leer(
                "  Desmarcar (indices separados por comas; vacio = confirmar "
                "todos): "
            ).strip()
        except EOFError:
            return list(planos)
        excluidos = set()
        for frag in excl.split(","):
            frag = frag.strip()
            if frag.isdigit():
                idx = int(frag)
                if 1 <= idx <= len(planos):
                    excluidos.add(idx)
        return [p for i, p in enumerate(planos, 1) if i not in excluidos]
    return list(planos)


def seleccionar_version(plan_dir, args, layout):
    """Devuelve el .nk elegido para el plano: mtime o override --use-version.

    ``--use-version V\\d+`` fuerza esa version (RC-SS-02, override no
    interactivo del falso positivo); si no existe => SinCompError nombrando
    la carpeta y las disponibles. Sin override: mejor_version_comp (mtime
    real + tie-break). Carpeta sin .nk calificante => SinCompError nombrando
    la carpeta (RC-SS-03: nunca skip silencioso).
    """
    if args.use_version:
        if not re.match(r"^V\d+$", args.use_version, re.IGNORECASE):
            raise SystemExit(
                "--use-version debe ser V\\d+ (ej. V015); se recibio %r."
                % args.use_version
            )
        return layouts.elegir_por_version(plan_dir, args.use_version, layout)
    return layouts.mejor_version_comp(plan_dir, layout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--comp", default="TEST_RENDER/prueba_test.nk")
    ap.add_argument("--wnode", default="Write1")
    ap.add_argument("--frames", type=int, default=90)
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--calib", type=int, default=6)
    ap.add_argument("--solo-calib", action="store_true")
    ap.add_argument("--to-suf", default=None,
                    help="sufijo TO_VFX (default: config central)")
    ap.add_argument("--comp-suf", default=None,
                    help="sufijo COMP (default: config central)")
    ap.add_argument("--from-suf", default=None,
                    help="sufijo FROM_VFX (default: config central)")
    ap.add_argument("--workers", default=None)
    ap.add_argument("--strat", action="store_true", default=True)
    ap.add_argument("--no-strat", action="store_false", dest="strat")
    ap.add_argument("--auto-range", action="store_true")
    ap.add_argument("--politica", default="ask",
                    choices=["ask", "keep", "replace", "corruptos"])
    ap.add_argument("--check-exr", action="store_true",
                    help="valida profundamente los EXR existentes con Nuke")
    ap.add_argument("--proyecto", default=None,
                    help="proyecto del layout (default: HTLR, con aviso)")
    ap.add_argument("--comp-dir", default=None,
                    help="carpeta de planos relativa a la base, o intencion")
    ap.add_argument("--resolve-latest", action="store_true",
                    help="confirma la seleccion por mtime sin preguntar")
    ap.add_argument("--use-version", default=None, metavar="V\\d+",
                    help="fuerza esa version .nk (override del falso positivo mtime)")
    ap.add_argument("--wnodes", default=None,
                    help="nodos Write reales del comp (DELIVERY_EXR/DELIVERY_DWG/"
                         "REVIEW_REC709/SBS_REC709); default: rol de entrega")
    ap.add_argument("--force-exr", action="store_true",
                    help="fuerza salida EXR-sequence del nodo de entrega "
                         "conservando duracion y resolucion (RC-MN-03)")
    args = ap.parse_args()

    # Infraestructura desde la config central estricta: workers, bases por SO
    # y sufijos por defecto. El CLI solo sobreescribe los sufijos por corrida.
    config = render_config.obtener_config_efectiva()

    # ---- Flujo asistido (PR1): layout + seleccion por mtime ----
    # Legacy sin flags nuevos => este bloque no corre (RC-QC-04).
    if es_flujo_asistido(args):
        args.proyecto, _ = resolver_proyecto(args.proyecto)
        layout = layouts.obtener_layout(args.proyecto)
        planos = planos_del_proyecto(args, config)
        if not planos:
            raise SystemExit(
                "Sin planos bajo %r: revisa la intencion o --comp-dir."
                % (args.comp_dir or "")
            )
        planos = confirmar_planos(planos, args)
        elegidos = {}
        for plano in planos:
            abs_dir = layouts.ruta_bajo_base(plano, config)
            if not abs_dir:
                raise SystemExit("Sin base local para resolver %r." % plano)
            try:
                version = seleccionar_version(abs_dir, args, layout)
            except layouts.SinCompError as e:
                raise SystemExit("ABORTA: %s" % e)
            elegidos[plano] = version
        print("\n== SELECCION POR MTIME ==")
        for plano, version in elegidos.items():
            print("  %s -> %s" % (plano, version))
        if len(elegidos) == 1:
            plano, version = next(iter(elegidos.items()))
            args.comp = plano.rstrip("/") + "/" + version
            print("  Comp seleccionado: %s" % args.comp)
        else:
            print(
                "  %d planos seleccionados: el flujo actual rinde UN comp "
                "por invocacion; repeti con --comp-dir apuntando a uno solo."
                % len(elegidos)
            )
            return
        args.auto_range = True  # el rango sale de la PROBE del comp elegido

    workers = filtrar_por_nombre(construir_workers(config["workers"]), args.workers)
    sufijos = sufijos_efectivos(
        config["sufijos"], args.to_suf, args.comp_suf, args.from_suf
    )
    args.to_suf, args.comp_suf, args.from_suf = (
        sufijos["TO_SUF"], sufijos["COMP_SUF"], sufijos["FROM_SUF"]
    )

    # ---- PROBE: rango del PLATE + nodos Write descubiertos ----
    pr = None
    if args.auto_range:
        print("== PROBE (detectar rango del PLATE y nodos) ==", flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(workers)) as ex:
            fut = {ex.submit(probar, w, args): w["nombre"] for w in workers}
            for f in concurrent.futures.as_completed(fut):
                nombre = fut[f]
                pr = f.result()
                if pr.get("nodes"):
                    print("  %-10s -> plate=%s-%s root=%sx%s@%sfps nodos=[%s]"
                          % (nombre, pr.get("plate_first"), pr.get("plate_last"),
                             pr.get("root_w") or "-", pr.get("root_h") or "-",
                             pr.get("root_fps"), ", ".join(sorted(pr["nodes"]))),
                          flush=True)
                else:
                    print("  %-10s -> plate=%s-%s write=%s-%s file=%s"
                          % (nombre, pr.get("plate_first"), pr.get("plate_last"),
                             pr.get("wnode_first"), pr.get("wnode_last"),
                             pr.get("wnode_file")), flush=True)
        if pr and pr.get("plate_first") and pr.get("plate_last"):
            args.start = int(pr["plate_first"])
            args.frames = int(pr["plate_last"]) - args.start + 1
            print("  Rango del PLATE: %d-%d (%d frames)"
                  % (args.start, args.start + args.frames - 1, args.frames), flush=True)
        elif pr and pr.get("wnode_first") and pr.get("wnode_last"):
            args.start = int(pr["wnode_first"])
            args.frames = int(pr["wnode_last"]) - args.start + 1
            print("  Rango del Write: %d-%d (%d frames)"
                  % (args.start, args.start + args.frames - 1, args.frames), flush=True)

    # ---- Multi-nodo (PR2, D4): descubre Write reales y arma el plan por nodo ----
    # Legacy (solo --comp) sigue el camino de abajo intacto (RC-QC-04).
    nodos_plan = {}
    mov_pendientes = []
    multi_nodo = bool(args.wnodes or args.force_exr or es_flujo_asistido(args))
    if multi_nodo and pr and pr.get("nodes"):
        nodos_probe = pr["nodes"]
        en_scope = filtrar_wnodes(nodos_probe, args.wnodes)
        exigir_delivery_exr(en_scope)  # CALIB/PLAN exigen el nodo de entrega EXR
        args.wnode = "DELIVERY_EXR"    # calib/plan/render apuntan a la entrega
        args.wnodes = ",".join(en_scope) if en_scope else None
        args.piggyback = env_piggyback(
            nodos_probe, en_scope, args.start, args.start + args.frames - 1
        )
        print("\n== NODOS DESCUBIERTOS ==")
        print("  %s" % ", ".join(sorted(nodos_probe)))
        print("== ALCANCE (%s) ==" % (", ".join(en_scope) or "ninguno"))
        inicio, fin = args.start, args.start + args.frames - 1
        for nombre in en_scope:
            info = nodos_probe[nombre]
            template = template_local(
                forzar_template_exr(info.get("file")) if args.force_exr
                else derivar_template(info.get("file")), config)
            if not template:
                print("  %-14s sin file evaluado (skip)" % nombre)
                continue
            e_i, e_f = rango_efectivo_nodo(info, inicio, fin)
            plan = plan_nodo(info, template, e_i, e_f, args.politica)
            nodos_plan[nombre] = plan
            if plan["tipo"] == "sequence":
                print("  %-14s EXR [%d..%d] existentes=%d faltantes=%d (%s)"
                      % (nombre, e_i, e_f, len(plan["existentes"]),
                         len(plan["a_render"]), plan["decision"]))
            else:
                print("  %-14s archivo %s (%s)"
                      % (nombre, os.path.basename(template), plan["decision"]))
                if plan["a_render"]:
                    mov_pendientes.append((nombre, e_i, e_f))
        if ("DELIVERY_EXR" not in nodos_plan
                or nodos_plan["DELIVERY_EXR"]["tipo"] != "sequence"):
            raise SystemExit(
                "Nodo de entrega DELIVERY_EXR sin template EXR: no hay frames "
                "a distribuir (revisa el Write o --force-exr)."
            )

    # ---- EXISTENTES + POLITICA ----
    existentes = []
    corruptos = set()
    if multi_nodo and nodos_plan:
        plan_exr = nodos_plan["DELIVERY_EXR"]
        existentes = plan_exr["existentes"]
        corruptos = set(plan_exr["corruptos"])
        if args.check_exr and existentes:
            paths = [p for n, p in existentes]
            print("== CHECK EXR (profundo, con Nuke) ==", flush=True)
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(workers)) as ex:
                fut = {ex.submit(check_profundo, w, args, paths): w["nombre"]
                       for w in workers}
                for f in concurrent.futures.as_completed(fut):
                    corruptos |= f.result()
        decision = plan_exr["decision"]
        a_render = plan_exr["a_render"]
    else:
        template = template_local(derivar_template((pr or {}).get("wnode_file")), config)
        if template:
            existentes = frames_existentes(template, args.start, args.start + args.frames - 1)
            sin_header = [n for n, p in existentes if not header_exr_valido(p)]
            corruptos = set(sin_header)
            if args.check_exr and existentes:
                paths = [p for n, p in existentes]
                print("== CHECK EXR (profundo, con Nuke) ==", flush=True)
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(workers)) as ex:
                    fut = {ex.submit(check_profundo, w, args, paths): w["nombre"]
                           for w in workers if w["nombre"] in [x["nombre"] for x in workers]}
                    for f in concurrent.futures.as_completed(fut):
                        corruptos |= f.result()
        decision, a_render = politica_reemplazo(args, existentes, corruptos)
    print("== POLITICA ==")
    print("  Decision: %s | existentes=%d corruptos=%d a_renderizar=%d"
          % (decision, len(existentes), len(corruptos), len(a_render)), flush=True)
    # Multi-nodo: no re-llenar el rango (el plan por nodo ya decidio).
    if not a_render and not nodos_plan:
        a_render = list(range(args.start, args.start + args.frames))
    if not a_render and not mov_pendientes:
        print("  Nada que renderizar (todo ya exportado y valido).")
        return

    if a_render:
        # ---- CALIB sobre los frames a renderizar (solo nodo de entrega) ----
        print("== CALIBRACION (workers: %s) ==" % ", ".join(w["nombre"] for w in workers), flush=True)
        calibs = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(workers)) as ex:
            fut = {ex.submit(calibrar, w, args, a_render): w["nombre"] for w in workers}
            for f in concurrent.futures.as_completed(fut):
                c = f.result()
                calibs[c["worker"]] = c
                cb = c.get("calib") or {}
                fallo = ""
                if cb.get("error"):
                    fallo = "  <ERROR: %s>" % cb
                print("  %-10s startup=%ss load=%ss per_frame=%ss perf_w=%s perf_r=%s%s"
                      % (c["worker"], c.get("startup_s"), cb.get("load_s"),
                         cb.get("per_frame_s"), cb.get("perf_write"), cb.get("perf_read"),
                         fallo), flush=True)

        costes = []
        for w in workers:
            cb = calibs.get(w["nombre"], {}).get("calib") or {}
            a = calibs.get(w["nombre"], {}).get("startup_s", 0) + cb.get("load_s", 0)
            b = cb.get("per_frame_s", 1e9)
            costes.append((a, b))
        t_min, ns = repartir(len(a_render), costes)

        print("\n== PLAN ==")
        print("  Frames a renderizar: %d | Tiempo estimado optimo: %.2fs" % (len(a_render), t_min))
        idx = 0
        asignaciones = {}
        for i, w in enumerate(workers):
            n = ns[i]
            if n <= 0:
                print("  %-10s -> sin frames (no se lanza)" % w["nombre"])
                continue
            bloque = a_render[idx:idx + n]
            idx += n
            asignaciones[w["nombre"]] = bloque
            print("  %-10s -> %d frames [%d..%d] | estimado %.2fs"
                  % (w["nombre"], len(bloque), bloque[0], bloque[-1],
                     costes[i][0] + costes[i][1] * len(bloque)))

        if args.solo_calib:
            return

        print("\n== RENDER ==", flush=True)
        reales = {}
        if asignaciones:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(asignaciones)) as ex:
                fut = {
                    ex.submit(rendir, w, args, asignaciones[w["nombre"]]): w["nombre"]
                    for w in workers
                    if w["nombre"] in asignaciones
                }
                for f in concurrent.futures.as_completed(fut):
                    r = f.result()
                    reales[r["worker"]] = r
                    print("  %-10s %4d frames | real=%ss (nuke=%s)"
                          % (r["worker"], r["frames"], r["real_s"], r.get("render_s")), flush=True)

        print("\n== RESUMEN ==")
        plan_total = max(
            costes[i][0] + costes[i][1] * len(asignaciones[w["nombre"]])
            for i, w in enumerate(workers)
            if w["nombre"] in asignaciones
        )
        real_total = max(r.get("real_s", 0) for r in reales.values()) if reales else 0
        print("  Planificado (max esperado): %.2fs" % plan_total)
        print("  Real (max medido):          %.2fs" % real_total)
        if decision == "replace":
            print("  ATENCION: se re-renderizaron TODOS los frames (politica replace).")

    # ---- Archivos unicos (MOV): render entero por nodo, sin reparto ----
    for nombre, e_i, e_f in mov_pendientes:
        print("\n== RENDER ARCHIVO (%s) ==" % nombre, flush=True)
        res = rendir_archivo(workers[0], args, nombre, e_i, e_f)
        print("  %s -> %s real=%ss (nuke=%s, rc=%s)"
              % (res["worker"], nombre, res["real_s"],
                 res.get("render_s"), res["rc"]), flush=True)


if __name__ == "__main__":
    main()