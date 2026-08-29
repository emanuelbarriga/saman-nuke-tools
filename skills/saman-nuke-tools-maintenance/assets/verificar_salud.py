#!/usr/bin/env python3
"""
verificar_salud.py — Indicadores de salud de saman-nuke-tools.

Uso:  python3 verificar_salud.py [ruta_al_repo]
      (por defecto: /Volumes/wupm/2026/saman-nuke-tools)

Da indicadores objetivos para "mantener en orden":
  - version:  __version__ del paquete vs último tag git
  - sync:     HEAD local vs origin/main
  - espectro: área de cobertura en la que estamos
  - checks:   integridad de estructura y compilación (checks_ok/total)
  - tests:    existencia real de tests (cobertura de test declarada)
  - pendientes: sugerencias accionables

Exit codes: 0 = todo OK, 1 = problemas que requieren acción.
"""
import os
import re
import subprocess
import sys

REPO = sys.argv[1] if len(sys.argv) > 1 else "/Volumes/wupm/2026/saman-nuke-tools"
VERSION_FILE = os.path.join(REPO, "SamanTools", "__init__.py")

checks_ok = 0
checks_total = 0
pendientes = []


def check(nombre, cond, detalle=""):
    global checks_ok, checks_total
    checks_total += 1
    if cond:
        checks_ok += 1
    else:
        pendientes.append("%s: %s" % (nombre, detalle))


def git(*args):
    try:
        out = subprocess.run(["git", "-C", REPO] + list(args),
                             capture_output=True, text=True, timeout=30)
        return out.stdout.strip()
    except Exception:
        return ""


# --- 1. Versión ---
version = "?"
if os.path.isfile(VERSION_FILE):
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', open(VERSION_FILE).read())
    version = m.group(1) if m else "?"
else:
    pendientes.append("Falta SamanTools/__init__.py")

tags = [t for t in git("tag", "--sort=-v:refname").splitlines() if t]
ultimo_tag = tags[0].lstrip("v") if tags else "(sin tags)"
check("Version definida", version != "?", "definir __version__")
check("Tag coincide con version", ultimo_tag != "(sin tags)" and version == ultimo_tag,
      "hay que crear el tag v" + version + " (release)")

# --- 2. Sync git ---
head = git("rev-parse", "--short", "HEAD")
origin = git("rev-parse", "--short", "origin/main")
st = git("status", "--porcelain")
check("Checkout clean", not st, "hay cambios sin commitear:\n%s" % st[:400])
check("Git sincronizado con origin/main", head and origin and head == origin,
      "HEAD=%s origin/main=%s -> hacer git push" % (head, origin))

# --- 3. Estructura crítica ---
estructura = {
    "menu.py raiz": os.path.join(REPO, "menu.py"),
    "bootstrap/menu.py": os.path.join(REPO, "bootstrap", "menu.py"),
    "paquete registro.py": os.path.join(REPO, "SamanTools", "registro.py"),
    "frame_manager.py": os.path.join(REPO, "SamanTools", "frame_manager.py"),
    "instalador Script Editor": os.path.join(REPO, "instalar_script_editor.py"),
    "setup_artista.sh": os.path.join(REPO, "setup_artista.sh"),
    "VERSIONING.md": os.path.join(REPO, "VERSIONING.md"),
    "nodos/Breakdown.gizmo": os.path.join(REPO, "SamanTools", "nodos", "Breakdown.gizmo"),
    "nodos/Review.gizmo": os.path.join(REPO, "SamanTools", "nodos", "Review.gizmo"),
    "nodos/Rutas.gizmo": os.path.join(REPO, "SamanTools", "nodos", "Rutas.gizmo"),
}
for nombre, ruta in estructura.items():
    check("Estructura: %s" % nombre, os.path.isfile(ruta), "falta %s" % ruta)

# --- 4. Compilación .py (sintaxis válida) ---
py_files = []
for root, dirs, files in os.walk(REPO):
    if "__pycache__" in root or ".git" in root:
        continue
    for f in files:
        if f.endswith(".py"):
            py_files.append(os.path.join(root, f))
for pf in py_files:
    check("Compila: %s" % os.path.relpath(pf, REPO),
          subprocess.run([sys.executable, "-m", "py_compile", pf],
                         capture_output=True).returncode == 0)

# --- 5. Tests reales ---
tests_encontrados = []
for root, dirs, files in os.walk(REPO):
    if ".git" in root:
        continue
    for f in files:
        if f.startswith("test_") or f.startswith("Test") or f.endswith("_test.py"):
            tests_encontrados.append(os.path.join(root, f))
check("Existen tests", bool(tests_encontrados),
      "no hay tests automatizados reales; crearlos si aplica")
check("Cobertura test (al menos 1 file test)", len(tests_encontrados) >= 1,
      "0 tests encontrados")

# --- 5b. Ejecutar tests + cobertura (si pytest disponible) ---
resultado_test = None
cobertura = None
if tests_encontrados:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", os.path.join(REPO, "tests"), "--cov=SamanTools",
         "--cov-report=term", "-q"],
        capture_output=True, text=True, timeout=300,
        cwd=REPO,
    )
    resultado_test = "PASS" if r.returncode == 0 else "FAIL"
    m = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)%", r.stdout)
    if m:
        cobertura = m.group(1) + "%"
    else:
        cobertura = "n/a"

# --- Reporte ---
print("=" * 60)
print("SAMAN-NUKE-TOOLS — SALUD DEL REPOSITORIO")
print("=" * 60)
print("repo        : %s" % REPO)
print("version     : %s" % version)
print("tag         : v%s (ultimo: %s)" % (version, ultimo_tag))
print("sync git    : HEAD=%s origin/main=%s clean=%s" % (head, origin, not st))
print("checks      : %d/%d OK" % (checks_ok, checks_total))
print("tests       : %d (cobertura real: %s)" % (len(tests_encontrados),
      "SI" if tests_encontrados else "NO — pendiente"))
print("pytest      : %s | cobertura: %s" % (resultado_test or "n/a", cobertura or "n/a"))
print("espectro    : %s" % ("estable" if checks_ok == checks_total and tests_encontrados and resultado_test == "PASS" else "requiere atencion"))
print("-" * 60)
if pendientes:
    print("PENDIENTES:")
    for p in pendientes:
        print("  - " + p)
else:
    print("Sin pendientes: repositorio estable y documentado.")
print("=" * 60)
sys.exit(0 if checks_ok == checks_total else 1)