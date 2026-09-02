"""Guard anti-fuga del batch render (T7): los archivos versionados no llevan
datos reales del estudio.

Escanea los archivos TRACKEADOS relevantes del batch (``render_distribuido/*``,
``README.md`` y los tests del batch) contra:

1. IPs literales (``192.168``, ``10.0``, ``172.16-31``) en TODO el scope.
2. Pares usuario-host ``@[a-z]`` en TODO el scope, EXCLUYENDO decorators
   (lineas que empiezan con ``@``: ``@pytest.fixture``, ``@tech...``) — el
   gotcha de T7 documentado en apply-progress.
3. Raices reales del storage (``/Volumes/wupm``, ``/mnt/wupm``) SOLO en
   archivos NO-test de ``render_distribuido``: los tests usan las rutas de
   ejemplo del spec; la plantilla publica y el README usan rutas ficticias y
   ``{base}`` generico (no reales).

El propio guard NO se escanea a si mismo: su codigo contiene las regex
(``192\\.168``, ``@[a-z]``, ``/Volumes/wupm``...) como literales y daria
falsos positivos.
"""

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# Archivos escaneados (relativos a la raiz del repo). Todos deben estar
# TRACKEADOS: el commit del batch los incluye (verificado en apply).
ARCHIVOS_BATCH = [
    "render_distribuido/render_config.py",
    "render_distribuido/render_distribuido.py",
    "render_distribuido/render_worker.py",
    "render_distribuido/layouts.py",
    "render_distribuido/plate_qc.py",
    "render_distribuido/hello.py",
    "render_distribuido/studio_config.example.json",
    "render_distribuido/README.md",
    "tests/test_render_config.py",
    "tests/test_render_worker.py",
    "tests/test_render_distribuido.py",
    "tests/test_layouts.py",
    "tests/test_seleccion.py",
    "tests/test_multinodo.py",
    "tests/test_qc_plate.py",
]

# Raices reales del estudio: se verifican SOLO en archivos de produccion
# (no-test) de render_distribuido, no en los tests (rutas de ejemplo del spec).
ARCHIVOS_PRODUCCION = [p for p in ARCHIVOS_BATCH if p.startswith("render_distribuido/")]

IP_RE = re.compile(r"192\.168|10\.0|172\.(?:1[6-9]|2\d|3[01])")
USUARIO_HOST_RE = re.compile(r"@[a-z]")
RAIZ_ESTUDIO_RE = re.compile(r"/Volumes/wupm|/mnt/wupm")


def _archivo(ruta):
    path = REPO / ruta
    assert path.is_file(), "Archivo escaneado ausente (debe estar versionado): %s" % ruta
    return path


def _hallazgos(ruta, regex, ignorar_decoradores=False):
    """[(numero, texto)] con match de regex en el archivo."""
    contenido = _archivo(ruta).read_text(encoding="utf-8")
    resultado = []
    for num, linea in enumerate(contenido.splitlines(), start=1):
        if ignorar_decoradores and linea.strip().startswith("@"):
            continue  # decorator (@pytest.fixture / @tech...): no es un usuario
        if regex.search(linea):
            resultado.append((num, linea.strip()))
    return resultado


def test_archivos_del_batch_trackeados_existen():
    """Todos los archivos del scope estan versionados (nada escaneado fantasma)."""
    for ruta in ARCHIVOS_BATCH:
        assert (REPO / ruta).is_file(), ruta


@pytest.mark.parametrize("ruta", ARCHIVOS_BATCH)
def test_sin_ips_en_archivos_del_batch(ruta):
    """0 IPs literales (192.168 / 10.0 / 172.16-31) en el batch."""
    hallazgos = _hallazgos(ruta, IP_RE)
    assert hallazgos == [], "%s: IPs literales: %s" % (ruta, hallazgos)


@pytest.mark.parametrize("ruta", ARCHIVOS_BATCH)
def test_sin_pares_usuario_host_en_archivos_del_batch(ruta):
    """0 pares usuario@host (los decorators @pytest/@tech no cuentan)."""
    hallazgos = _hallazgos(ruta, USUARIO_HOST_RE, ignorar_decoradores=True)
    assert hallazgos == [], "%s: pares usuario@host: %s" % (ruta, hallazgos)


@pytest.mark.parametrize("ruta", ARCHIVOS_PRODUCCION)
def test_sin_raices_reales_del_estudio_en_produccion(ruta):
    """0 literales /Volumes/wupm o /mnt/wupm en codigo/docs NO-test.

    La plantilla publica y el README usan rutas ficticias y ``{base}``
    generico; los tests del batch pueden usar las rutas de ejemplo del spec.
    """
    hallazgos = _hallazgos(ruta, RAIZ_ESTUDIO_RE)
    assert hallazgos == [], "%s: raices reales del estudio: %s" % (ruta, hallazgos)


def test_plantilla_publica_sin_ips_y_hosts_hostname():
    """Spec 'No IPs in public template': hosts son hostnames, sin IPs."""
    ejemplo = json.loads(
        (REPO / "render_distribuido" / "studio_config.example.json").read_text(
            encoding="utf-8"
        )
    )
    for worker in ejemplo["workers"]:
        ssh = worker["ssh"]
        if ssh is None:
            continue  # worker local
        assert IP_RE.search(ssh) is None, "host con IP literal: %s" % ssh
        assert "." in ssh, "host no es hostname: %s" % ssh


def test_readme_documenta_acl_d8():
    """Spec 'ACL documented' (D8): admin WRITE + worker READ + fallback local."""
    readme = (REPO / "render_distribuido" / "README.md").read_text(encoding="utf-8")
    assert "WRITE" in readme
    assert "READ" in readme
    assert ".saman/studio_config.json" in readme
    assert "RENDER_LOCAL_CONFIG" in readme