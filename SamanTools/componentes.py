"""Manifiesto único de lo que integra la distribución verificable.

Las rutas son relativas al repositorio para que el generador pueda validarlas y
copiarlas sin depender de la máquina donde se ejecute.

v3.0.0 publica exactamente los cinco nodos rehechos —Rutas, Breakdown, Review,
ColorSpaces y fSpy— más el bootstrap de actualización y las utilidades de menú
que no son nodos. Todo lo demás queda afuera de la superficie: los archivos
siguen en el repositorio (S12), pero no entran al `dist` ni al menú.
"""

COMPONENTES = (
    {
        "id": "rutas",
        "etiqueta": "Rutas (rutas VFX dinámicas)",
        "modulos": ("SamanTools/rutas_unico.py",),
        "assets": ("SamanTools/nodos/Rutas.gizmo",),
        "tests": ("tests/test_rutas_unico.py",),
        "activo": True,
    },
    {
        "id": "breakdown",
        "etiqueta": "Breakdown (frames por tabla)",
        "modulos": (),
        "assets": ("SamanTools/nodos/Breakdown.gizmo",),
        "tests": ("tests/test_breakdown_knobs.py",),
        "activo": True,
    },
    {
        "id": "review",
        "etiqueta": "Review (comparación de dos elementos)",
        "modulos": (),
        "assets": ("SamanTools/nodos/Review.gizmo",),
        "tests": ("tests/test_limpiar.py",),
        "activo": True,
    },
    {
        "id": "colorspaces",
        "etiqueta": "ColorSpaces (clasifica Reads por espacio de color)",
        "modulos": (),
        "assets": ("SamanTools/nodos/ColorSpaces.gizmo",),
        "tests": ("tests/test_colorspaces_gizmo.py",),
        "activo": True,
    },
    {
        "id": "fspy",
        "etiqueta": "fSpy (cámara calibrada desde una foto)",
        "modulos": (),
        "assets": ("SamanTools/nodos/fSpy.gizmo", "SamanTools/fSpy.svg"),
        "tests": ("tests/test_fspy_nodos.py",),
        "activo": True,
    },
    {
        "id": "acerca_de",
        "etiqueta": "Acerca de SamanTools",
        "modulos": ("SamanTools/registro.py",),
        "assets": ("SamanTools/Saman.svg",),
        "tests": ("tests/test_menu.py", "tests/test_registro.py"),
        "activo": True,
    },
    {
        "id": "actualizacion",
        "etiqueta": "Actualización",
        "modulos": ("bootstrap/menu.py",),
        "assets": (),
        "tests": ("tests/test_bootstrap_menu.py",),
        "activo": True,
    },
    {
        "id": "nodos_proyecto",
        "etiqueta": "Nodos por proyecto",
        "modulos": ("SamanTools/proyecto.py",),
        "assets": (),
        "tests": ("tests/test_proyecto.py",),
        "activo": True,
    },
)

#: Fuera de la superficie v3. Siguen en el repositorio y en el historial: no se
#: borran archivos en esta entrega, sólo se les quita la entrada en el menú y en
#: el dist. Si alguno resultara ser dependencia de un componente activo, el build
#: lo informa en vez de incluirlo en silencio.
EXCLUIDOS = {
    "SamanTools/panel_comentarios.py": "Panel VFXFlow fuera del alcance v3.",
    "SamanTools/vfxflow_auth.py": "Autenticación VFXFlow fuera del alcance v3.",
    "SamanTools/vfxflow_config.py": "Configuración VFXFlow fuera del alcance v3.",
    "SamanTools/vfxflow_datos.py": "Datos VFXFlow fuera del alcance v3.",
    "SamanTools/sesion_vfxflow.py": "Sesión VFXFlow fuera del alcance v3.",
    "SamanTools/diagnostico_red.py": "Diagnóstico de red fuera del alcance v3.",
    "render_distribuido/": "Render distribuido fuera del alcance v3.",
    "SamanTools/rutas.py": "Lógica del nodo Rutas v1: reemplazada por rutas_unico.py.",
    "SamanTools/rutas_global.py": "Shim del panel global de rutas, retirado.",
    "SamanTools/cambiar_colorspace.py": "Reemplazado por el nodo ColorSpaces.",
    "SamanTools/breakdown_datos.py": "Capa de datos del Breakdown v1, embebida en el gizmo v2.",
    "SamanTools/nodos/Rutas.nk": "El nodo Rutas v3 es un .gizmo autocontenido.",
}
