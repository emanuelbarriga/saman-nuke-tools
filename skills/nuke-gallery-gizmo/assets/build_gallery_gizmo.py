#!/usr/bin/env python3
"""
Generador de galerias Nuke (gizmo) desde una carpeta de assets del proyecto HTLR.

Replica el patron funcional y visual de MuzzleHTLR.gizmo:
  - Group con knobs: Categoria (menu), Elemento por categoria (menu),
    Show Grid (oculto), Ver Nombres, Resolution Multiplier.
  - Un stack Read->Grade->Premult->Text2 por cada asset (Text2 = nombre).
  - ContactSheet por categoria + ContactSheet "Todos (Grid General)".
  - Switch por categoria (elemento individual) + Switch principal
    (categoria * 2 + grid) + Output.

Modelo de conexiones (verificado en MuzzleHTLR.gizmo y .nk reales):
  - Cada stack termina capturando su salida:  set $Nref [stack 0]
  - Los `push $ref` van INMEDIATAMENTE ANTES del nodo que los consume.
  - Un nodo con `inputs N` conecta input N-1 .. input 0 con los refs
    empujados: el ULTIMO push = input 0.
    Por eso los pushes se emiten en orden inverso al deseado.
  - Inputs del Switch principal (menu categoria indice i, "Todos" = N):
      input 2i   = switch de elemento de la categoria i
      input 2i+1 = contact sheet de la categoria i
      input 2N   = contact sheet "Todos"
    which:  parent.categoria == N ? 2N : parent.categoria*2 + show_grid

Uso:
  python3 build_gallery_gizmo.py <assets_dir> [opciones]

  <assets_dir>: ruta absoluta o relativa a GLOBAL_ASSETS
    (ej.: "MUZZLE FLASHES VOL 2" o "MUZZLE FLASHES VOL 2/9mm_Pistol_2469/PNG").

Opciones:
  --name <nombre>         Nombre del grupo .gizmo (default: carpeta origen).
  --out <archivo.gizmo>   Ruta de salida (default: COMP/Scripts/<slug>.gizmo).
  --global-assets <dir>   Raiz GLOBAL_ASSETS.
  --split-by-token        En carpetas planas, agrupar por token del nombre
                          (Angled|Front|Off-Center|Side|...).
  --split-by-prefix       En carpetas planas, agrupar por prefijo del nombre
                          antes del primer numero (ej. Continuous_Landing,
                          Falling_Sparks_Bokeh, Sparks_Landing_High_Angle).
  --colorspace <cs>       Colorspace para reads de imagen (default: color_picking).
  --no-colorspace         No escribir knob colorspace.
"""

import argparse
import os
import re
import subprocess
import sys

IMAGE_EXTS = {".png", ".exr", ".tif", ".tiff", ".jpg", ".jpeg", ".dpx", ".cin"}
VIDEO_EXTS = {".mov", ".mp4", ".mxf"}

CATEGORY_TOKENS = ["Angled", "Front", "Off-Center", "Side",
                   "Semi-Auto", "Automatic", "Continuous", "Burst",
                   "Splatter", "Slash", "Diagonal", "Upward", "Wall",
                   "Ground", "Bokeh", "Falling", "Small", "Large"]

ROWS_EXPR = r'{{"\[expr \{int( (sqrt( \[numvalue inputs] ) ) )\} ] * \[expr \{int( ceil ( (\[numvalue inputs] /(sqrt( \[numvalue inputs] ) ) )) )\} ] < \[numvalue inputs]    ? \[expr \{int( (sqrt( \[numvalue inputs] ) ) )\} ] +1 : \[expr \{int( (sqrt( \[numvalue inputs] ) ) )\} ]"}}'
COLS_EXPR = r'{{"\[expr \{int( ceil ( (\[numvalue inputs] /(sqrt( \[numvalue inputs] )) )) )\} ]"}}'


def slugify(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
    return s or "cat"


def natsort_key(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


_PROBE_CACHE: dict = {}


def _probe_header(path: str):
    """ffprobe width,height,nb_frames de una sola llamada -> (w, h, nf) o (None,None,None)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,nb_frames", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=20, check=True,
        ).stdout.strip().split(",")
        w, h = int(out[0]), int(out[1])
        nf = None
        if len(out) > 2:
            raw = out[2].strip()
            if raw and raw.lstrip("-").isdigit() and int(raw) > 0:
                nf = int(raw)
        return w, h, nf
    except Exception:
        return None, None, None


def _probe_count_frames(path: str):
    """Conteo EXACTO de frames decodificando con -count_frames (nb_read_frames)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
             "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=120, check=True,
        ).stdout.strip()
        n = int(out) if out.lstrip("-").isdigit() else 0
        return n if n > 0 else None
    except Exception:
        return None


def probe_meta(path: str):
    """Devuelve (width, height, n_frames) reales del asset, cacheado por path.

    n_frames viene de nb_frames del header; si no es fiable, se decodifica el
    clip con -count_frames (nb_read_frames) para un conteo exacto.
    """
    if path in _PROBE_CACHE:
        return _PROBE_CACHE[path]
    w, h, nf = _probe_header(path)
    if nf is None:
        nf = _probe_count_frames(path)
    _PROBE_CACHE[path] = (w, h, nf)
    return w, h, nf


def probe_format(path: str) -> str:
    """Devuelve el string de formato Nuke 'W H 0 0 W H 1 NAME' segun resolucion real."""
    w, h, _ = probe_meta(path)
    if w is None or h is None:
        w, h = 3840, 2160
    names = {(3840, 2160): "UHD_4K", (4096, 2160): "4K_DCP",
             (2048, 1080): "2K_DCP", (1920, 1080): "HD_1080p",
             (1280, 720): "HD_720p"}
    name = names.get((w, h), "custom")
    return f"{w} {h} 0 0 {w} {h} 1 {name}"


def discover(assets_dir: str, split_by_token: bool, split_by_prefix: bool):
    """Devuelve (cat_order, cats). cats[categoria] = [(filename, relpath, ext), ...]."""
    files = []
    for root, dirs, fnames in os.walk(assets_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in sorted(fnames, key=natsort_key):
            ext = os.path.splitext(f)[1].lower()
            if ext in IMAGE_EXTS or ext in VIDEO_EXTS:
                rel = os.path.relpath(os.path.join(root, f), assets_dir)
                files.append((f, rel, ext))
    if not files:
        return [], {}

    subdirs = [d for d in sorted(os.listdir(assets_dir))
               if not d.startswith(".")
               and os.path.isdir(os.path.join(assets_dir, d))
               and any(os.path.splitext(x)[1].lower() in IMAGE_EXTS | VIDEO_EXTS
                       for x in os.listdir(os.path.join(assets_dir, d)))]

    cats = {}
    if subdirs and not split_by_token and not split_by_prefix:
        for d in subdirs:
            items = [it for it in files if it[1].startswith(d + os.sep)]
            if items:
                cats[d] = items
        loose = [it for it in files if not any(it[1].startswith(d + os.sep) for d in cats)]
        if loose:
            cats["Otros"] = loose
    elif split_by_prefix:
        # Carpeta plana: agrupar por prefijo del nombre antes del primer numero.
        prefix_groups = {}
        loose = []
        for it in files:
            name = os.path.splitext(it[0])[0]
            prefix = "_".join(p for p in name.split("_")
                               if p and not p[0].isdigit()
                               and not re.match(r"\((\d+)\)$", p))
            if prefix:
                prefix_groups.setdefault(prefix, []).append(it)
            else:
                loose.append(it)
        if prefix_groups:
            cats.update(prefix_groups)
        if loose:
            cats["Otros"] = loose
        if not cats:
            cats["Todos"] = files
    else:
        # Carpeta plana: agrupar por token de categoria en el nombre.
        tokenized = {}
        loose = []
        for it in files:
            name = os.path.splitext(it[0])[0]
            cat = next((t for t in CATEGORY_TOKENS
                        if re.search(r"(^|[_\-\s])" + re.escape(t) + r"([_\-\s]|$)", name, re.I)),
                       None)
            if cat:
                tokenized.setdefault(cat, []).append(it)
            else:
                loose.append(it)
        if tokenized:
            cats.update(tokenized)
        if loose:
            cats["Otros"] = loose
        if not cats:
            cats["Todos"] = files

    priority = {"Angled": 0, "Front": 1, "Off-Center": 2, "Side": 3}
    cat_order = sorted(cats.keys(), key=lambda c: (priority.get(c, 99), c.lower()))
    return cat_order, cats


def esc_brackets(s: str) -> str:
    """Nuke guarda corchetes '[' escapados en .nk/.gizmo."""
    return s.replace("[", "\\[")


def esc_nuke(s: str) -> str:
    """Escapa corchetes Y llaves como lo hace Nuke al serializar
    (ej. rutas dinamicas: '\\\\[python \\\\{PYTHON_COMP\\\\}]/...')."""
    return s.replace("[", "\\[").replace("{", "\\{").replace("}", "\\}")


def stack_lines(idx: int, fname: str, rel: str, ext: str, file_expr: str,
                format_str: str, colorspace: str, xoff: int, nframes=None):
    """Devuelve lineas del stack Read->Grade->Premult->Text2 para un asset."""
    is_video = ext in VIDEO_EXTS
    msg = esc_brackets("[file rootname [file tail [value [topnode].file]]]")
    L = []
    L.append(" Read {")
    L.append("  inputs 0")
    L.append(f"  file_type {ext.lstrip('.')}")
    L.append(f'  file "{file_expr}"')
    L.append(f'  format "{format_str}"')
    if is_video and nframes:
        L.append("  first 1")
        L.append(f"  last {nframes}")
        L.append(f"  origlast {nframes}")
        L.append("  origset true")
    elif not is_video:
        L.append("  origset true")
    L.append("  version 1")
    if colorspace:
        L.append(f"  colorspace {colorspace}")
    L.append(f"  name gal_read_{idx}")
    L.append(f"  xpos {xoff}")
    L.append("  ypos -140")
    L.append(" }")
    L.append(" Grade {")
    L.append(f"  name gal_grade_{idx}")
    L.append(f"  xpos {xoff}")
    L.append("  ypos -40")
    L.append(" }")
    L.append(" Premult {")
    L.append(f"  name gal_premult_{idx}")
    L.append(f"  xpos {xoff}")
    L.append("  ypos -16")
    L.append(" }")
    L.append(" Text2 {")
    L.append("  font_size_toolbar 100")
    L.append("  font_width_toolbar 100")
    L.append("  font_height_toolbar 100")
    L.append(f'  message "{msg}"')
    L.append("  box {0 0 {input.width} {input.height}}")
    L.append("  transforms {")
    L.append("   {0 2}")
    L.append("  }")
    L.append("  cursor_position 50")
    L.append("  center {{input.width/2} {input.height/2}}")
    L.append("  cursor_initialised true")
    L.append("  autofit_bbox false")
    L.append("  initial_cursor_position {")
    L.append("   {0 2160}")
    L.append("  }")
    L.append("  group_animations {")
    L.append("   {0}")
    L.append("   imported:")
    L.append("   0")
    L.append("   selected:")
    L.append("   items:")
    L.append("   \"root transform/\"")
    L.append("  }")
    L.append("  animation_layers {")
    L.append("   {1 11 2048 1080 0 0 1 1 0 0 0 0}")
    L.append("  }")
    L.append(f"  name gal_text_{idx}")
    L.append(f"  xpos {xoff}")
    L.append("  ypos 8")
    L.append("  disable {{!parent.boolean}}")
    L.append(" }")
    return L


def build(cats: dict, cat_order: list, assets_dir: str, group_name: str,
          global_assets: str, colorspace: str) -> list:
    gassets_rel = os.path.relpath(os.path.abspath(assets_dir), os.path.abspath(global_assets))
    gassets_rel = gassets_rel.replace(os.sep, "/")

    out = ["version 17.1 v1"]
    # ---------------- Group + knobs ----------------
    out.append(" Group {")
    out.append("  inputs 0")
    out.append(f"  name {group_name}")
    kc = ["n = nuke.thisNode()", "k = nuke.thisKnob()", "kn = k.name()",
          "if kn == 'categoria':", "    cat = n['categoria'].value()",
          "    n['show_grid'].setValue(True)"]
    for c in cat_order:
        kc.append(f"    n['elem_{slugify(c)}'].setVisible(cat == '{c}')")
    kc.append("elif kn in [" + ", ".join(f"'elem_{slugify(c)}'" for c in cat_order) + "]:")
    kc.append("    n['show_grid'].setValue(False)")
    out.append(f'  knobChanged "{esc_brackets("\\n".join(kc))}"')
    out.append("  label Gallery")
    out.append("  selected true")
    out.append("  xpos 0")
    out.append("  ypos 0")
    out.append("  addUserKnob {20 tab l Visualización}")
    cats_menu = " ".join(f'"{c}"' for c in cat_order) + ' "Todos (Grid General)"'
    out.append(f"  addUserKnob {{4 categoria l Categoría M {{{cats_menu}}}}}")
    out.append(f"  categoria {cat_order[0]}")
    out.append("  addUserKnob {6 show_grid l \"Show Grid\" +HIDDEN +STARTLINE}")
    out.append("  show_grid true")
    for i, c in enumerate(cat_order):
        hidden = " +HIDDEN" if i != 0 else ""
        items = " ".join(f'"{os.path.splitext(f)[0]}"' for f, _, _ in cats[c])
        out.append(f"  addUserKnob {{4 elem_{slugify(c)} l Elemento{hidden} M {{{items}}}}}")
    out.append("  addUserKnob {6 boolean l \"Ver Nombres\" +STARTLINE}")
    out.append("  boolean true")
    out.append("  addUserKnob {26 Espacio l \"  \" T \"   \"}")
    out.append("  addUserKnob {41 firstFrame l \"First Frame\" T FrameHold1.firstFrame}")
    out.append("  addUserKnob {41 setToCurrentFrame l \"Set to Current Frame\" -STARTLINE T FrameHold1.setToCurrentFrame}")
    out.append("  addUserKnob {6 use_frame l \"Usar Frame Hold\" +STARTLINE}")
    out.append("  use_frame false")
    out.append("  addUserKnob {20 Settings l \"Contact Sheet Settings\"}")
    out.append("  addUserKnob {7 resMult l \"Resolution Multiplier\" R 0.1 2}")
    out.append("  resMult 1")
    out.append(" }")

    # ---------------- stacks (una por asset) ----------------
    refs = {}  # (cat, filename) -> ref
    idx = 0
    xoff = -200
    for c in cat_order:
        for fname, rel, ext in cats[c]:
            file_expr = (esc_nuke("[python {PYTHON_COMP}]/GLOBAL_ASSETS/")
                         + gassets_rel + "/" + rel.replace(os.sep, "/"))
            w, h, nframes = probe_meta(os.path.join(assets_dir, rel))
            format_str = probe_format(os.path.join(assets_dir, rel))
            out += stack_lines(idx, fname, rel, ext, file_expr, format_str,
                               colorspace, xoff, nframes)
            ref = f"N{idx:08x}"
            out.append(f"set {ref} [stack 0]")
            refs[(c, fname)] = ref
            idx += 1
            xoff -= 120

    def push_reversed(rlist):
        for r in reversed(rlist):
            out.append(f"push ${r}")

    # ---------------- ContactSheet ALL ----------------
    all_keys = [(c, f) for c in cat_order for f, _, _ in cats[c]]
    all_refs = [refs[k] for k in all_keys]
    push_reversed(all_refs)
    out.append(" ContactSheet {")
    out.append(f"  inputs {len(all_refs)}")
    out.append("  width {{input.width*columns*resMult}}")
    out.append("  height {{input.height*rows*resMult}}")
    out.append(f"  rows {ROWS_EXPR}")
    out.append(f"  columns {COLS_EXPR}")
    out.append("  center true")
    out.append("  roworder TopBottom")
    out.append("  name gal_cs_all")
    out.append("  tile_color 0xff69f7ff")
    out.append("  xpos -163")
    out.append("  ypos 121")
    out.append(" }")
    out.append("set gall [stack 0]")

    cs_refs, sw_refs = {}, {}
    for i, c in enumerate(cat_order):
        c_refs = [refs[(c, f)] for f, _, _ in cats[c]]
        cs_slug = f"g{slugify(c)}"
        sw_slug = f"s{slugify(c)}"

        # ContactSheet de la categoria (pushes antes del nodo)
        push_reversed(c_refs)
        out.append(" ContactSheet {")
        out.append(f"  inputs {len(c_refs)}")
        out.append("  width {{input.width*columns*resMult}}")
        out.append("  height {{input.height*rows*resMult}}")
        out.append(f"  rows {ROWS_EXPR}")
        out.append(f"  columns {COLS_EXPR}")
        out.append("  center true")
        out.append("  roworder TopBottom")
        out.append(f"  name gal_cs_{slugify(c)}")
        out.append("  tile_color 0xff69f7ff")
        out.append(f"  xpos {-298 - i * 120}")
        out.append("  ypos 121")
        out.append(" }")
        out.append(f"set {cs_slug} [stack 0]")

        # Switch de elemento individual (menu elem_<cat>)
        push_reversed(c_refs)
        out.append(" Switch {")
        out.append(f"  inputs {len(c_refs)}")
        out.append(f"  which {{{{{'parent.elem_' + slugify(c)}}}}}")
        out.append(f"  name gal_sw_{slugify(c)}")
        out.append(f"  xpos {-533 - i * 120}")
        out.append("  ypos 121")
        out.append(" }")
        out.append(f"set {sw_slug} [stack 0]")

        cs_refs[c] = cs_slug
        sw_refs[c] = sw_slug

    # ---------------- Switch principal ----------------
    n = len(cat_order)
    # inputs deseados: por categoria (sw, cs) intercalados + ALL al final
    # (input 2i = sw de categoria i, input 2i+1 = cs de categoria i, input 2N = ALL)
    desired = []
    for c in cat_order:
        desired.append(sw_refs[c])
        desired.append(cs_refs[c])
    desired.append("gall")
    push_reversed(desired)
    out.append(" Switch {")
    out.append(f"  inputs {2 * n + 1}")
    which = f'parent.categoria == {n} ? {2 * n} : parent.categoria * 2 + (parent.show_grid ? 1 : 0)'
    out.append('  which {{"' + which + '"}}')
    out.append("  name gal_main")
    out.append("  xpos -978")
    out.append("  ypos 322")
    out.append(" }")
    out.append("set gmain [stack 0]")

    # ---------------- Crop -> Reformat -> FrameHold -> Output ----------------
    out.append("push $gmain")
    out.append(" Crop {")
    out.append("  name Crop1")
    out.append("  xpos -978")
    out.append("  ypos 346")
    out.append(" }")
    out.append(" Reformat {")
    out.append("  name Reformat1")
    out.append("  xpos -978")
    out.append("  ypos 370")
    out.append(" }")
    out.append(" FrameHold {")
    out.append("  firstFrame 25")
    out.append("  name FrameHold1")
    out.append("  xpos -978")
    out.append("  ypos 394")
    out.append("  disable {{!parent.use_frame}}")
    out.append(" }")
    out.append(" Output {")
    out.append("  inputs 1")
    out.append("  name Output1")
    out.append("  xpos -978")
    out.append("  ypos 438")
    out.append(" }")
    out.append("end_group")
    return out


def main():
    ap = argparse.ArgumentParser(description="Genera un gizmo de galeria Nuke desde assets.")
    ap.add_argument("assets_dir", help="Carpeta de assets (absoluta o relativa a GLOBAL_ASSETS).")
    ap.add_argument("--name", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--global-assets", default="/Volumes/wupm/2026/HTLR/COMP/GLOBAL_ASSETS")
    ap.add_argument("--split-by-token", action="store_true")
    ap.add_argument("--split-by-prefix", action="store_true")
    ap.add_argument("--colorspace", default="color_picking")
    ap.add_argument("--no-colorspace", action="store_true")
    args = ap.parse_args()

    global_assets = os.path.abspath(args.global_assets)
    if not os.path.isabs(args.assets_dir):
        candidate = os.path.join(global_assets, args.assets_dir)
        assets_dir = candidate if os.path.isdir(candidate) else args.assets_dir
    else:
        assets_dir = args.assets_dir
    if not os.path.isdir(assets_dir):
        print(f"ERROR: no existe la carpeta {assets_dir}", file=sys.stderr)
        sys.exit(1)

    colorspace = None if args.no_colorspace else args.colorspace
    split = args.split_by_prefix or args.split_by_token
    cat_order, cats = discover(assets_dir, split, args.split_by_prefix)
    if not cat_order:
        print("ERROR: sin assets validos en la carpeta.", file=sys.stderr)
        sys.exit(1)

    group_name = args.name or os.path.basename(os.path.normpath(assets_dir))
    result = build(cats, cat_order, assets_dir, group_name, global_assets, colorspace)

    if args.out:
        out_path = args.out
    else:
        out_path = os.path.join(os.path.dirname(global_assets), "Scripts",
                                f"{slugify(group_name)}.gizmo")
    texto = "\n".join(result)
    try:
        from SamanTools.limpiar import sanitizar_texto_nk
        texto = sanitizar_texto_nk(texto)
    except ImportError:
        pass  # SamanTools no accesible: el generador en si no produce knobs volatiles
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(texto)

    total = sum(len(v) for v in cats.values())
    print(f"OK  {out_path}")
    print(f"    Grupo: {group_name} | Categorias: {', '.join(cat_order)} | Assets: {total}")


if __name__ == "__main__":
    main()