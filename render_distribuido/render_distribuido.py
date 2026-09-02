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
import subprocess
import sys
import time

try:
    from render_distribuido import render_config
except ImportError:  # script mode: sys.path[0] es la carpeta render_distribuido
    import render_config


def ruta_repo(worker):
    return worker["base"] + "/saman-nuke-tools/render_distribuido"


def construir_workers(config_workers):
    """Convierte los workers de la config central a la forma interna.

    ``ssh`` se compone como ``ssh_user + "@" + host`` SOLO cuando el worker es
    remoto (``ssh`` no nulo/vacio); local queda ``None``. ``bin`` pasa a ser
    ``nuke_exec`` de la config; ``base`` y ``lc_all`` se copian tal cual.
    """
    workers = []
    for w in config_workers:
        ssh = "%s@%s" % (w["ssh_user"], w["ssh"]) if w["ssh"] else None
        workers.append(
            {
                "nombre": w["nombre"],
                "ssh": ssh,
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
    if mode in ("probe",):
        pass
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


# ---------------------------------------------------------------------------
# Frames existentes / validacion / politica de reemplazo
# ---------------------------------------------------------------------------

PAD_EXPR = re.compile(r"#+|\%0\d+d")
TEMPLATE_EXPR = re.compile(r"(\d{4})(?=\.exr$)")


def derivar_template(sample):
    """Convierte ...V05.0747.exr (sample evaluado) en ...V05.####.exr."""
    if not sample:
        return None
    return TEMPLATE_EXPR.sub("####", sample, count=1)


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
    """Check barato: header magico EXR ('v/1\\1') + tamano minimo."""
    try:
        if not os.path.isfile(path):
            return False
        if os.path.getsize(path) < 1024:
            return False
        with open(path, "rb") as f:
            return f.read(4) == b"v/1\x01"
    except OSError:
        return False


def frames_existentes(template, inicio, fin):
    por_frame = []
    for n in range(inicio, fin + 1):
        p = path_frame(template, n)
        if os.path.isfile(p):
            por_frame.append((n, p))
    return por_frame


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
    args = ap.parse_args()

    # Infraestructura desde la config central estricta: workers, bases por SO
    # y sufijos por defecto. El CLI solo sobreescribe los sufijos por corrida.
    config = render_config.obtener_config_efectiva()
    workers = filtrar_por_nombre(construir_workers(config["workers"]), args.workers)
    sufijos = sufijos_efectivos(
        config["sufijos"], args.to_suf, args.comp_suf, args.from_suf
    )
    args.to_suf, args.comp_suf, args.from_suf = (
        sufijos["TO_SUF"], sufijos["COMP_SUF"], sufijos["FROM_SUF"]
    )

    # ---- PROBE: rango del PLATE + patron de salida ----
    pr = None
    if args.auto_range:
        print("== PROBE (detectar rango del PLATE) ==", flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(workers)) as ex:
            fut = {ex.submit(probar, w, args): w["nombre"] for w in workers}
            for f in concurrent.futures.as_completed(fut):
                nombre = fut[f]
                pr = f.result()
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

    # ---- EXISTENTES + POLITICA ----
    existentes = []
    corruptos = set()
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
    if decision in ("keep", "corruptos") and not a_render:
        print("  Nada que renderizar (todo ya exportado y valido).")
        return
    if not a_render:
        a_render = list(range(args.start, args.start + args.frames))

    # ---- CALIB sobre los frames a renderizar ----
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


if __name__ == "__main__":
    main()