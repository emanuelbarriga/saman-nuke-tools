"""layouts - Layouts declarativos multi-proyecto (D1/D2 del design).

Los roles semanticos fijos (PLATE, DELIVERY, PREVIEW, SBS) se mapean a
patrones fisicos de carpetas por proyecto como DATOS relativos a la base del
config (RC-CN-05): cero raices absolutas, cero IPs, cero tokens de
usuario-host => seguro para test_no_fuga. La config solo habilita/deshabilita
proyectos (RC-CN-02); las intenciones no literales (``2VFX/Capitulo_7``) se
remapean al patron real del proyecto (RC-SS-01). La seleccion de version usa
el mtime REAL del SO medido en el orquestador, nunca en workers (RC-SS-02:
LucidLink colapsa ctime/birthtime).

Solo stdlib; sin dependencia de Nuke ni de la unidad montada.
"""

import os
import platform
import re
from dataclasses import dataclass
from typing import Callable

# Carpeta de fecha de plate: YYYYMMDD con sufijo opcional -N (RC-QC-01).
PATRON_FECHA = re.compile(r"^\d{8}(?:-\d+)?$")

# Patron generico de .nk candidato cuando no se pasa layout (default seguro).
PATRON_COMP_GENERICO = re.compile(r"_comp_SAMAN_.*\.nk$", re.IGNORECASE)


class SinCompError(Exception):
    """Carpeta sin .nk calificante (o version pedida ausente): abort con nombre.

    La politica del flujo es estricta: nunca skip silencioso; el mensaje
    nombra la carpeta y, cuando aplica, las versiones disponibles.
    """

    def __init__(self, plan_dir, detalle=""):
        self.plan_dir = plan_dir
        self.detalle = detalle
        mensaje = "Sin .nk calificante en %s" % plan_dir
        if detalle:
            mensaje += ". %s" % detalle
        super().__init__(mensaje)


class SinPlateError(Exception):
    """Sin carpeta de fecha de plate bajo el patron del layout (RC-QC-01)."""

    def __init__(self, carpeta):
        self.carpeta = carpeta
        super().__init__("No hay carpeta de fecha de plate en %s" % carpeta)


@dataclass(frozen=True)
class Layout:
    """Layout declarativo de un proyecto: patrones RELATIVOS a la base.

    - raiz: prefijo del proyecto relativo a la base (ej. ``HTLR/``).
    - episodio: mapea la intencion del usuario al episodio/secuencia real.
    - comps: patron de carpeta de planos, con placeholder ``{ep}``.
    - plate / entrega: patrones fisicos de plate y entrega, con placeholders
      ``{ep}``, ``{fecha}``, ``{plan}`` y ``{tipo}``.
    - patron_comp: regex del .nk candidato del proyecto (case-insensitive).
    - version_re: regex del numero ``_V\\d+``; vacio => proyecto sin
      numeracion (IPYD), el tie-break cae a -1 (design D2).
    """

    raiz: str
    episodio: Callable[[str], str]
    comps: str
    plate: str
    entrega: str
    patron_comp: str
    version_re: str


# ---------------------------------------------------------------------------
# Remapeo de intenciones a episodios/secuencias (D1)
# ---------------------------------------------------------------------------


def _ultimo_numero(intent):
    """Devuelve el ultimo numero entero de la intencion, o None."""
    numeros = re.findall(r"\d+", intent)
    return int(numeros[-1]) if numeros else None


def _episodio_htlr(intent):
    """'Capitulo 7' / '2VFX/Capitulo_12' -> 'EP_07' / 'EP_12'."""
    n = _ultimo_numero(intent)
    if n is None:
        raise SystemExit(
            "Intencion %r no tiene episodio numerico (HTLR: 'Capitulo N')."
            % intent
        )
    return "EP_%02d" % n


def _episodio_ipyd(intent):
    """'104' -> '104' (episodios numericos 101..106, sin padding)."""
    n = _ultimo_numero(intent)
    if n is None:
        raise SystemExit(
            "Intencion %r no tiene episodio numerico (IPYD: '104')." % intent
        )
    return "%d" % n


def _episodio_pcf(intent):
    """'SC13' / 'PFC_SC13' -> 'PFC_SC13' (idempotente)."""
    match = re.search(r"SC(\d+)", intent, re.IGNORECASE)
    if not match:
        raise SystemExit(
            "Intencion %r no tiene secuencia SC## (PCF)." % intent
        )
    return "PFC_SC%02d" % int(match.group(1))


LAYOUTS = {
    "HTLR": Layout(
        raiz="HTLR/",
        episodio=_episodio_htlr,
        comps="COMP/{ep}/",
        plate="TO_VFX/{ep}/{fecha}/{plan}.mov",
        entrega="FROM_VFX/{ep}/{fecha}/{tipo}/",
        patron_comp=r"_comp_SAMAN_V\d+\.nk$",
        version_re=r"_V(\d+)",
    ),
    "IPYD": Layout(
        raiz="IPYD/",
        episodio=_episodio_ipyd,
        comps="COMP/{ep}/",
        plate="TO_VFX/{ep}/{fecha}/{plan}.mov",
        entrega="FROM_VFX/{ep}/{fecha}/{tipo}/",
        patron_comp=r"_COMP_SAMAN_SE\.nk$",
        version_re="",
    ),
    "PCF": Layout(
        raiz="PCF/",
        episodio=_episodio_pcf,
        comps="COMP/{ep}/",
        plate="FROM_VFX/{ep}/{fecha}/{plan}.mov",
        entrega="FROM_VFX/{ep}/{fecha}/{tipo}/",
        patron_comp=r"_comp_SAMAN_V\d+\.nk$",
        version_re=r"_V(\d+)",
    ),
}


def obtener_layout(proyecto):
    """Devuelve el Layout de un proyecto; desconocido => SystemExit claro."""
    try:
        return LAYOUTS[proyecto]
    except KeyError:
        raise SystemExit(
            "Proyecto %r no tiene layout declarado (declarados: %s)."
            % (proyecto, ", ".join(sorted(LAYOUTS)))
        )


def fecha_key(fecha):
    """Clave ordenable de una carpeta de fecha YYYYMMDD[-N] (RC-QC-01).

    La parte YYYYMMDD domina; el sufijo -N ordena como revision mas reciente
    del mismo dia: ``20260628-2`` > ``20260628`` > ``20260627``.
    """
    base, sep, sufijo = str(fecha).partition("-")
    return (int(base), int(sufijo) if sep else 0)


# ---------------------------------------------------------------------------
# Base local y proyectos habilitados (D1, RC-CN-02)
# ---------------------------------------------------------------------------


def _base_local(config):
    """Base declarada del SO del orquestador en bases_por_so, o None."""
    so = platform.system()
    clave = {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}.get(so, so)
    bases = config.get("bases_por_so") if isinstance(config, dict) else None
    if isinstance(bases, dict):
        valor = bases.get(clave)
        if isinstance(valor, str):
            return valor
    return None


def _habilitado(proyecto, config):
    """True si el proyecto esta habilitado en config['proyectos'] (RC-CN-02)."""
    proyectos = config.get("proyectos") if isinstance(config, dict) else None
    return isinstance(proyectos, dict) and proyectos.get(proyecto) is True


def ruta_bajo_base(relativa, config):
    """Ruta absoluta de una relativa bajo la base local, o None (D1)."""
    base = _base_local(config)
    if not base or not relativa:
        return None
    return os.path.normpath(os.path.join(base, relativa))


def resolver_planos(intent, proyecto, config):
    """Carpetas de planos RELATIVAS a la base para la intencion (RC-SS-01).

    Solo proyectos habilitados resuelven (config['proyectos']); la intencion
    se remapea al patron real del proyecto (``2VFX/Capitulo_7`` -> ``EP_07``)
    y las carpetas de planos se enumeran bajo {base}{raiz}{comps} del
    episodio. Aborta (SystemExit) si el proyecto no esta habilitado, si la
    base local no esta declarada o si la intencion no mapea a un episodio.
    """
    layout = obtener_layout(proyecto)
    if not _habilitado(proyecto, config):
        raise SystemExit(
            "Proyecto %r no esta habilitado: agrega %r: true en la clave "
            "'proyectos' de studio_config.json." % (proyecto, proyecto)
        )
    base = _base_local(config)
    if not base:
        raise SystemExit(
            "Sin base declarada para el SO local (%s) en bases_por_so: "
            "revisa studio_config.json." % platform.system()
        )
    ep = layout.episodio(intent)
    carpeta_ep = layout.raiz + layout.comps.format(ep=ep)
    carpeta_abs = os.path.join(base, carpeta_ep)
    if not os.path.isdir(carpeta_abs):
        raise SystemExit(
            "Sin carpeta de planos %r bajo la base: revisa la intencion o el "
            "layout del proyecto." % carpeta_ep
        )
    planos = []
    for nombre in sorted(os.listdir(carpeta_abs)):
        if os.path.isdir(os.path.join(carpeta_abs, nombre)):
            planos.append(carpeta_ep + nombre)
    return planos


def localizar_plate(layout, plano, config, fecha=None):
    """Ruta RELATIVA del plate: carpeta de fecha mas reciente u override.

    (RC-QC-01): escanea {base}{raiz}<prefijo plate> por carpetas
    YYYYMMDD[-N]; la mas reciente por fecha_key gana por defecto y `fecha`
    sobreescribe. Sin carpeta de fecha => SinPlateError nombrando la ruta
    (nunca silencioso).
    """
    base = _base_local(config)
    if not base:
        raise SystemExit(
            "Sin base declarada para el SO local en bases_por_so: revisa "
            "studio_config.json."
        )
    plan = os.path.basename(plano.rstrip("/")) if plano else ""
    ep = _episodio_de_plano(layout, plano)
    prefijo = layout.plate.split("{fecha}")[0].format(ep=ep)
    carpeta_ep = layout.raiz + prefijo
    carpeta_abs = os.path.join(base, carpeta_ep)
    fechas = []
    try:
        for nombre in sorted(os.listdir(carpeta_abs)):
            ruta = os.path.join(carpeta_abs, nombre)
            if PATRON_FECHA.match(nombre) and os.path.isdir(ruta):
                fechas.append(nombre)
    except OSError:
        pass
    if fecha is None:
        if not fechas:
            raise SinPlateError(carpeta_ep)
        fecha = max(fechas, key=fecha_key)
    return "%s%s/%s.mov" % (carpeta_ep, fecha, plan)


def _episodio_de_plano(layout, plano):
    """Episodio/secuencia del plano: el segmento entre comps y el plan.

    Soportado con o sin la raiz del proyecto: ``HTLR/COMP/EP_07/<plan>`` y
    ``COMP/EP_07/<plan>`` resuelven ambos a ``EP_07``.
    """
    prefijo_comps = layout.comps.split("{ep}")[0]
    resto = plano
    if resto.startswith(layout.raiz):
        resto = resto[len(layout.raiz):]
    if resto.startswith(prefijo_comps):
        resto = resto[len(prefijo_comps):]
    return resto.split("/")[0]


# ---------------------------------------------------------------------------
# Seleccion de version por mtime real (D2, RC-SS-02)
# ---------------------------------------------------------------------------


def _compilar_patron(layout):
    """Regex del .nk candidato: por proyecto o generica si no hay layout."""
    if layout is None:
        return PATRON_COMP_GENERICO
    return re.compile(layout.patron_comp, re.IGNORECASE)


def _compilar_version(layout):
    """Regex de la version _V del proyecto; None si no numera versiones."""
    if layout is None or not layout.version_re:
        return None
    # case-insensitive: las versiones reales alternan _V/_v (plan_..._v001.nk).
    return re.compile(layout.version_re, re.IGNORECASE)


def _version(nombre, layout=None):
    """Numero _V del archivo, o -1 si el proyecto no numera versiones."""
    rxv = _compilar_version(layout)
    if rxv is None:
        return -1
    match = rxv.search(nombre)
    return int(match.group(1)) if match else -1


def _es_ignorable(nombre):
    """True si el archivo se descarta: .nk~, autosave, puntos, temporales.

    Clasificacion adversarial (threat matrix): `.nk~`, `.autosave`, `.tmp`
    y dotfiles jamas cuentan como version de comp.
    """
    if nombre.startswith("."):
        return True
    bajo = nombre.lower()
    return (
        bajo.endswith(".nk~")
        or ".autosave" in bajo
        or bajo.endswith(".tmp")
    )


def _candidatas(plan_dir, layout=None):
    """Nombres de .nk calificantes del proyecto en la carpeta (ordenados).

    Carpeta inaccesible o sin tal directorio => SinCompError nombrando la
    carpeta (politica estricta: nunca skip silencioso).
    """
    try:
        lista = os.listdir(plan_dir)
    except OSError as e:
        raise SinCompError(plan_dir, detalle="no legible (%s)" % e)
    patron = _compilar_patron(layout)
    nombres = []
    for nombre in sorted(lista):
        if _es_ignorable(nombre):
            continue
        if patron.search(nombre):
            nombres.append(nombre)
    return nombres


def _mtime(plan_dir, nombre):
    """mtime REAL del SO del archivo (orquestador; LucidLink colapsa ctime)."""
    return os.path.getmtime(os.path.join(plan_dir, nombre))


def analizar_version(plan_dir, layout=None):
    """Seleccion por mtime real: {elegida, candidatas, sospechosa} (RC-SS-02).

    La elegida es la de mayor mtime del SO con tie-break de ``_V\\d+`` mayor;
    ``sospechosa=True`` cuando la elegida por mtime NO es la de mayor ``_V``
    (falso positivo tipico: v001 tocado hoy vs v015 aprobado hace un mes),
    que el CLI ofrece resolver con ``--use-version``. Carpeta sin .nk
    calificante => SinCompError nombrando la carpeta (RC-SS-03).
    """
    candidatas = _candidatas(plan_dir, layout)
    if not candidatas:
        raise SinCompError(plan_dir)
    elegida = max(
        candidatas,
        key=lambda c: (_mtime(plan_dir, c), _version(c, layout), c),
    )
    mayor_v = max(_version(c, layout) for c in candidatas)
    sospechosa = mayor_v > 0 and _version(elegida, layout) < mayor_v
    return {
        "elegida": elegida,
        "candidatas": candidatas,
        "sospechosa": sospechosa,
    }


def mejor_version_comp(plan_dir, layout=None):
    """Devuelve el .nk de mayor mtime SO real (tie-break _V) (RC-SS-02)."""
    return analizar_version(plan_dir, layout)["elegida"]


def elegir_por_version(plan_dir, vtag, layout=None):
    """Fuerza la version V\\d+ pedida (override no interactivo, RC-SS-02).

    Si la version no existe entre las candidatas => SinCompError nombrando la
    carpeta, la version pedida y las disponibles (nunca silencioso).
    """
    candidatas = _candidatas(plan_dir, layout)
    objetivo = int(re.sub(r"\D", "", vtag) or "0")
    elegibles = [c for c in candidatas if _version(c, layout) == objetivo]
    if not elegibles:
        disponibles = ", ".join(
            str(v) for v in sorted(_version(c, layout) for c in candidatas)
        )
        raise SinCompError(
            plan_dir,
            detalle="version %s no encontrada; disponibles: %s"
            % (vtag, disponibles or "ninguna"),
        )
    return max(elegibles, key=lambda c: (_mtime(plan_dir, c), c))