"""
Tests de SamanTools.rutas_unico: política de un solo nodo de rutas por comp.

Corren sin Nuke, sobre el stub de `tests/conftest.py` y nodos falsos propios
(estilo de `tests/test_rutas.py`): lo que se verifica es comportamiento
observable — qué se detecta, qué se escribe, qué se borra y en qué orden.
"""

import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nuke
from SamanTools import rutas_unico as ru


# ---------------------------------------------------------------------------
# Nodos y knobs falsos
# ---------------------------------------------------------------------------


class Knob:
    """Knob falso con value/setValue, como el del stub."""

    def __init__(self, valor=""):
        self.valor = valor

    def value(self):
        return self.valor

    def setValue(self, v):
        self.valor = v


class Nodo:
    """Nodo falso: expone sólo lo que la política necesita."""

    def __init__(self, nombre="Nodo1", cls="Group", knobs=None):
        self._nombre = nombre
        self._cls = cls
        self.knobs_d = dict(knobs or {})
        self.posxy = (0, 0)
        self.enfocado = 0

    def name(self):
        return self._nombre

    def Class(self):
        return self._cls

    def knobs(self):
        return self.knobs_d

    def knob(self, nombre):
        return self.knobs_d.get(nombre)

    def __getitem__(self, nombre):
        return self.knobs_d[nombre]

    def setSelected(self, v):
        pass

    def xpos(self):
        return self.posxy[0]

    def ypos(self):
        return self.posxy[1]

    def setXYpos(self, x, y):
        self.posxy = (x, y)

    def showControlPanel(self):
        self.enfocado += 1

    def addKnob(self, knob):
        self.knobs_d[knob.nombre] = knob


class KnobConNombre(Knob):
    """Knob fabricado por nuke.Int_Knob(nombre, etiqueta) en los tests."""

    def __init__(self, nombre, etiqueta="", valor=""):
        Knob.__init__(self, valor)
        self.nombre = nombre
        self.etiqueta = etiqueta


class NodoRoto:
    """Nodo que explota al leer sus knobs: la política no puede caerse."""

    def name(self):
        return "Roto"

    def knobs(self):
        raise RuntimeError("sin knobs")

    def knob(self, nombre):
        raise RuntimeError("sin knobs")


# ---------------------------------------------------------------------------
# Constructores de estado
# ---------------------------------------------------------------------------


def _db(
    active="Mac",
    folders=None,
    users=None,
    **extra
):
    """Estado en el esquema nuevo derivado del gizmo RutasV2."""
    db = {
        "active_user": active,
        "folders": (
            folders
            if folders is not None
            else [
                {"id": "TO_VFX", "label": "Material Original", "knob": "folder_TO_VFX"},
                {"id": "COMP", "label": "Composiciones", "knob": "folder_COMP"},
            ]
        ),
        "users": (
            users
            if users is not None
            else {
                "Mac": {"TO_VFX": "/vol/Mac/TO_VFX/", "COMP": "/vol/Mac/COMP/"},
                "Linux": {"TO_VFX": "/mnt/TO_VFX/", "COMP": "/mnt/COMP/"},
            }
        ),
    }
    db.update(extra)
    return db


def _nodo_v2(nombre="RutasV2_1", db=None, ver=1, motor=None):
    """Nodo nuevo autocontenido: db_json (+ nodo_ver si `ver` no es None).

    `motor` permite meter en Cerebro_Python un motor falso ejecutable; por
    defecto el knob lleva un comentario, que no expone `rutas_engine`.
    """
    db = _db() if db is None else db
    knobs = {
        "db_json": Knob(json.dumps(db, indent=2)),
        "Cerebro_Python": Knob("# motor embebido" if motor is None else motor),
        "pulldown": Knob(db.get("active_user", "")),
    }
    if ver is not None:
        knobs["nodo_ver"] = Knob(ver)
    return Nodo(nombre, "Group", knobs)


def _nodo_viejo(nombre="Rutas1", usuario="MacServer", rutas=None, **otros):
    """Nodo legacy: UsuarioActivo + los knobs clásicos TO_VFX/comp/FROM_VFX."""
    rutas = (
        {
            "TO_VFX_SERVER_MAC": "/vol/TO_VFX/",
            "comp_SERVER_MAC": "/vol/COMP/",
            "FROM_VFX_SERVER_MAC": "/vol/FROM_VFX/",
        }
        if rutas is None
        else dict(rutas)
    )
    knobs = {"UsuarioActivo": Knob(usuario)}
    for nombre_knob, valor in rutas.items():
        knobs[nombre_knob] = Knob(valor)
    for nombre_knob, valor in otros.items():
        knobs[nombre_knob] = Knob(valor)
    return Nodo(nombre, "NoOp", knobs)


def _escena(nodos):
    """Deja el comp en el estado pedido y limpia los mensajes previos."""
    nuke._estado["nodos"] = list(nodos)
    nuke._estado["mensajes"] = []
    nuke._estado.pop("motor", None)
    return nodos


def _codigo_motor(falla=False):
    """Motor falso: expone `rutas_engine(action)` y anota cada acción.

    El motor embebido real se ejecuta con `exec(...)` y su entrada estable es
    `rutas_engine(action='sync')`; este doble hace lo mismo y deja la traza en
    el stub de nuke, que es lo observable.
    """
    lineas = [
        "import nuke",
        "",
        "",
        "def rutas_engine(action='sync', arg1=None):",
    ]
    if falla:
        lineas.append("    raise RuntimeError('motor roto')")
    else:
        lineas.append("    nuke._estado.setdefault('motor', []).append(action)")
    return "\n".join(lineas) + "\n"


def _llamadas_motor():
    """Acciones que el motor falso ejecutó desde el último _escena()."""
    return list(nuke._estado.get("motor", []))


def _instalar_delete(monkeypatch, eventos):
    """nuke.delete falso: registra el borrado y lo saca de la escena."""

    def borrar(nodo):
        eventos.append(("delete", nodo.name()))
        nuke._estado["nodos"] = [n for n in nuke._estado["nodos"] if n is not nodo]

    monkeypatch.setattr(nuke, "delete", borrar, raising=False)
    return eventos


def _instalar_ask(monkeypatch, respuesta, preguntas):
    """nuke.ask falso: registra la pregunta y responde lo pedido."""

    def preguntar(mensaje):
        preguntas.append(mensaje)
        return respuesta

    monkeypatch.setattr(nuke, "ask", preguntar, raising=False)
    return preguntas


def _instalar_paste(monkeypatch, pegar, pastes):
    """nuke.nodePaste falso: registra la ruta, delega y suma el nodo al comp."""

    def node_paste(ruta):
        pastes.append(ruta)
        nuevo = pegar(ruta)
        if nuevo is not None:
            nuke._estado["nodos"].append(nuevo)
        return nuevo

    monkeypatch.setattr(nuke, "nodePaste", node_paste, raising=False)
    return pastes


class KnobQueRegistra(Knob):
    """Knob que anota su escritura: sirve para verificar el orden escritura/borrado."""

    def __init__(self, valor, eventos):
        Knob.__init__(self, valor)
        self.eventos = eventos

    def setValue(self, v):
        self.eventos.append(("write", self.valor))
        Knob.setValue(self, v)


class KnobQueEscribeEnElMotor(Knob):
    """db_json que anota su escritura en la misma traza que el motor falso.

    Permite verificar que la sincronización ocurre DESPUÉS de escribir el
    estado fusionado."""

    def setValue(self, v):
        nuke._estado.setdefault("motor", []).append("write")
        Knob.setValue(self, v)


# ---------------------------------------------------------------------------
# S3/S4: detección por knobs, nunca por nombre
# ---------------------------------------------------------------------------


class TestDeteccion:
    def test_detecta_nodo_nuevo_por_db_json(self):
        assert ru.es_nodo_rutas(_nodo_v2()) is True

    def test_detecta_nodo_viejo_por_knobs_clasicos(self):
        assert ru.es_nodo_rutas(_nodo_viejo()) is True

    def test_detecta_viejo_con_cualquier_sufijo(self):
        for sufijo in ("MAC", "WINDOWS", "ARTIST"):
            n = _nodo_viejo(rutas={"TO_VFX_SERVER_" + sufijo: "/x/"})
            assert ru.es_nodo_rutas(n) is True

    def test_no_depende_del_nombre(self):
        # Un nodo de rutas renombrado se sigue detectando...
        assert ru.es_nodo_rutas(_nodo_v2(nombre="CualquierCosa")) is True
        assert ru.es_nodo_rutas(_nodo_viejo(nombre="Rutas7")) is True
        # ...y un nodo llamado "Rutas1" sin los knobs no es un nodo de rutas.
        falso = Nodo("Rutas1", "Read", {"file": Knob("/plano.exr")})
        assert ru.es_nodo_rutas(falso) is False

    def test_legacy_sin_usuario_activo_no_es_nodo_de_rutas(self):
        n = _nodo_viejo()
        del n.knobs_d["UsuarioActivo"]
        assert ru.es_nodo_rutas(n) is False

    def test_tolera_none_y_nodos_rotos(self):
        assert ru.es_nodo_rutas(None) is False
        assert ru.es_nodo_rutas(NodoRoto()) is False


# ---------------------------------------------------------------------------
# S4: marcador de versión
# ---------------------------------------------------------------------------


class TestVersion:
    def test_version_actual_con_nodo_ver_1(self):
        assert ru.es_version_actual(_nodo_v2(ver=1)) is True

    def test_version_anterior_con_otro_valor_o_sin_knob(self):
        assert ru.es_version_actual(_nodo_v2(ver=0)) is False
        assert ru.es_version_actual(_nodo_v2(ver=None)) is False
        assert ru.es_version_actual(_nodo_viejo()) is False

    def test_version_tolera_texto_guardado_en_el_comp(self):
        assert ru.es_version_actual(_nodo_v2(ver="1")) is True

    def test_version_tolera_none(self):
        assert ru.es_version_actual(None) is False


# ---------------------------------------------------------------------------
# S3: encontrar todos los nodos de rutas del comp
# ---------------------------------------------------------------------------


class TestEncontrar:
    def test_devuelve_solo_nodos_de_rutas_en_orden_del_comp(self):
        primero = _nodo_v2("RutasV2_1")
        read = Nodo("Read1", "Read", {"file": Knob("/plano.exr")})
        viejo = _nodo_viejo("Rutas1")
        ultimo = _nodo_v2("RutasV2_2")
        _escena([primero, read, viejo, ultimo])
        assert ru.encontrar_nodos_rutas() == [primero, viejo, ultimo]

    def test_sin_nodos_devuelve_lista_vacia(self):
        _escena([])
        assert ru.encontrar_nodos_rutas() == []


# ---------------------------------------------------------------------------
# S9: db_de normaliza el nodo nuevo y el viejo
# ---------------------------------------------------------------------------


class TestDbDeNodoNuevo:
    def test_parsea_el_esquema_del_gizmo(self):
        db = ru.db_de(_nodo_v2())
        assert db["active_user"] == "Mac"
        assert [f["id"] for f in db["folders"]] == ["TO_VFX", "COMP"]
        assert db["users"]["Mac"]["COMP"] == "/vol/Mac/COMP/"

    def test_conserva_claves_desconocidas(self):
        db_in = _db(nota="anotacion", users={"Mac": {"COMP": "/c/", "OTRO": "/o/"}})
        db_in["folders"].append({"id": "EXTRA", "label": "x", "knob": "folder_EXTRA", "propia": 1})
        db = ru.db_de(_nodo_v2(db=db_in))
        assert db["nota"] == "anotacion"
        assert db["users"]["Mac"]["OTRO"] == "/o/"
        assert db["folders"][2]["propia"] == 1

    def test_descarta_carpetas_sin_id_usable(self):
        db_in = _db()
        db_in["folders"].append({"label": "sin id"})
        db_in["folders"].append({"id": "  "})
        db = ru.db_de(_nodo_v2(db=db_in))
        assert [f["id"] for f in db["folders"]] == ["TO_VFX", "COMP"]

    def test_json_invalido_cae_a_los_knobs_clasicos(self):
        n = _nodo_viejo()
        n.knobs_d["db_json"] = Knob("{roto")
        db = ru.db_de(n)
        assert db["active_user"] == "MacServer"
        assert db["users"]["MacServer"]["TO_VFX"] == "/vol/TO_VFX/"
        assert db["legacy_knobs"]["db_json_crudo"] == "{roto"

    def test_json_invalido_sin_knobs_clasicos_da_estado_vacio(self):
        n = Nodo("X", "Group", {"db_json": Knob("{roto")})
        db = ru.db_de(n)
        assert db["active_user"] == ""
        assert db["folders"] == []
        assert db["users"] == {}
        assert db["legacy_knobs"]["db_json_crudo"] == "{roto"

    def test_none_da_estado_vacio(self):
        assert ru.db_de(None) == {"active_user": "", "folders": [], "users": {}}


class TestDbDeNodoViejo:
    def test_normaliza_rutas_y_usuario(self):
        db = ru.db_de(_nodo_viejo())
        assert db["active_user"] == "MacServer"
        assert [f["id"] for f in db["folders"]] == ["TO_VFX", "COMP", "FROM_VFX"]
        assert db["folders"][0] == {
            "id": "TO_VFX",
            "label": "Material Original",
            "knob": "folder_TO_VFX",
        }
        assert db["users"]["MacServer"] == {
            "TO_VFX": "/vol/TO_VFX/",
            "COMP": "/vol/COMP/",
            "FROM_VFX": "/vol/FROM_VFX/",
        }

    def test_conserva_knobs_crudos(self):
        n = _nodo_viejo(string="PALF", SO_Detectado="macOS", RutaActual="TO_VFX: /vol/")
        db = ru.db_de(n)
        assert db["legacy_knobs"]["string"] == "PALF"
        assert db["legacy_knobs"]["SO_Detectado"] == "macOS"
        assert db["legacy_knobs"]["RutaActual"] == "TO_VFX: /vol/"
        # El usuario crudo se conserva y los knobs ya interpretados no se copian.
        assert db["legacy_knobs"]["UsuarioActivo"] == "MacServer"
        assert "TO_VFX_SERVER_MAC" not in db["legacy_knobs"]

    def test_no_copia_knobs_estructurales_ni_vacios(self):
        n = _nodo_viejo(Cerebro_Python="codigo enorme", Vacio="")
        db = ru.db_de(n)
        assert "Cerebro_Python" not in db["legacy_knobs"]
        assert "Vacio" not in db["legacy_knobs"]
        assert "db_json" not in db["legacy_knobs"]

    def test_usuario_activo_sin_rutas_queda_como_usuario_vacio(self):
        n = Nodo("Rutas1", "NoOp", {"UsuarioActivo": Knob("Artist")})
        db = ru.db_de(n)
        assert db["active_user"] == "Artist"
        assert db["users"] == {"Artist": {}}
        assert db["folders"] == []


# ---------------------------------------------------------------------------
# S9: fusión pura
# ---------------------------------------------------------------------------


class TestFusionar:
    def test_union_de_carpetas_y_usuarios(self):
        base = _db()
        otro = _db(
            folders=[
                {"id": "TO_VFX", "label": "otra", "knob": "folder_TO_VFX"},
                {"id": "ASSETS", "label": "Assets", "knob": "folder_ASSETS"},
            ],
            users={"MacLocal": {"ASSETS": "/local/ASSETS/"}},
        )
        db = ru.fusionar_dbs([base, otro])
        assert [f["id"] for f in db["folders"]] == ["TO_VFX", "COMP", "ASSETS"]
        # Gana la definición de carpeta del superviviente.
        assert db["folders"][0]["label"] == "Material Original"
        assert set(db["users"]) == {"Mac", "Linux", "MacLocal"}

    def test_superviviente_conserva_sus_rutas_y_se_completan_las_que_faltan(self):
        base = _db(users={"Mac": {"COMP": "/superviviente/COMP/"}})
        otro = _db(
            folders=[{"id": "COMP", "label": "Composiciones", "knob": "folder_COMP"}],
            users={"Mac": {"COMP": "/otro/COMP/", "TO_VFX": "/otro/TO_VFX/"}},
        )
        db = ru.fusionar_dbs([base, otro])
        assert db["users"]["Mac"]["COMP"] == "/superviviente/COMP/"
        assert db["users"]["Mac"]["TO_VFX"] == "/otro/TO_VFX/"

    def test_no_pierde_claves_desconocidas(self):
        base = _db(nota="del superviviente")
        otro = _db(nota="del otro", extra={"a": 1})
        db = ru.fusionar_dbs([base, otro])
        assert db["nota"] == "del superviviente"
        assert db["extra"] == {"a": 1}

    def test_active_user_valido_se_conserva(self):
        base = _db(active="Linux")
        otro = _db(active="Mac")
        db = ru.fusionar_dbs([base, otro])
        assert db["active_user"] == "Linux"

    def test_active_user_invalido_cae_al_primer_usuario(self):
        base = _db(active="Fantasma")
        db = ru.fusionar_dbs([base])
        assert db["active_user"] == "Mac"

    def test_sin_usuarios_active_user_queda_vacio(self):
        db = ru.fusionar_dbs([_db(active="Mac", users={})])
        assert db["active_user"] == ""

    def test_no_modifica_las_entradas(self):
        base = _db()
        otro = _db(folders=[{"id": "ASSETS", "label": "Assets", "knob": "folder_ASSETS"}])
        copia_base = copy.deepcopy(base)
        copia_otro = copy.deepcopy(otro)
        ru.fusionar_dbs([base, otro])
        assert base == copia_base
        assert otro == copia_otro

    def test_sin_dbs_devuelve_estado_vacio(self):
        assert ru.fusionar_dbs([]) == {"active_user": "", "folders": [], "users": {}}
        assert ru.fusionar_dbs(None) == {"active_user": "", "folders": [], "users": {}}


# ---------------------------------------------------------------------------
# S8: superviviente
# ---------------------------------------------------------------------------


class TestSuperviviente:
    def test_gana_el_de_mas_contenido(self):
        chico = _nodo_v2("Chico", db=_db(users={"Mac": {}}))
        grande = _nodo_v2(
            "Grande",
            db=_db(
                folders=[{"id": "COMP", "label": "Composiciones", "knob": "folder_COMP"}],
                users={"Mac": {}, "Linux": {}, "Windows": {}},
            ),
        )
        assert ru.elegir_superviviente([chico, grande]) is grande

    def test_version_actual_gana_aunque_el_viejo_tenga_mas_contenido(self):
        viejo = _nodo_viejo("Viejo")
        actual = _nodo_v2("Actual", db=_db(folders=[], users={"Mac": {}}))
        assert ru.elegir_superviviente([viejo, actual]) is actual

    def test_empate_gana_el_primero_del_comp(self):
        primero = _nodo_v2("Primero")
        segundo = _nodo_v2("Segundo")
        assert ru.elegir_superviviente([primero, segundo]) is primero

    def test_lista_vacia_devuelve_none(self):
        assert ru.elegir_superviviente([]) is None
        assert ru.elegir_superviviente(None) is None


# ---------------------------------------------------------------------------
# S3, S7, S10, S11: el hook de carga
# ---------------------------------------------------------------------------


class TestPolitica:
    def test_cero_nodos_informa_nada_y_no_inserta(self, monkeypatch):
        _escena([])
        eventos = []
        monkeypatch.setattr(nuke, "createNode", lambda *a, **k: eventos.append("create"), raising=False)
        monkeypatch.setattr(nuke, "nodePaste", lambda *a, **k: eventos.append("paste"), raising=False)
        _instalar_delete(monkeypatch, eventos)
        r = ru.aplicar_politica_al_cargar()
        assert r["accion"] == "nada"
        assert r["nodos"] == 0
        assert r["superviviente"] is None
        assert eventos == []
        assert nuke._estado["nodos"] == []

    def test_un_nodo_actual_no_toca_nada(self, monkeypatch):
        n = _nodo_v2("RutasV2_1")
        _escena([n])
        antes = n.knobs_d["db_json"].value()
        eventos, preguntas = [], []
        _instalar_delete(monkeypatch, eventos)
        _instalar_ask(monkeypatch, True, preguntas)
        r = ru.aplicar_politica_al_cargar()
        assert r["accion"] == "unico"
        assert r["nodos"] == 1
        assert r["superviviente"] == "RutasV2_1"
        assert n.knobs_d["db_json"].value() == antes
        assert eventos == [] and preguntas == []

    def test_un_nodo_viejo_no_se_migra_ni_se_borra(self, monkeypatch):
        n = _nodo_viejo("Rutas1")
        _escena([n])
        eventos, preguntas = [], []
        _instalar_delete(monkeypatch, eventos)
        _instalar_ask(monkeypatch, True, preguntas)
        r = ru.aplicar_politica_al_cargar()
        assert r["accion"] == "unico"
        assert "anterior" in r["detalle"]
        assert "db_json" not in n.knobs_d
        assert eventos == [] and preguntas == []

    def test_dos_nodos_fusiona_y_borra_el_sobrante(self, monkeypatch):
        chico = _nodo_v2("Chico", db=_db(users={"Mac": {"COMP": "/chico/COMP/"}}))
        grande = _nodo_v2("Grande", db=_db(extra={"nota": "x"}))
        _escena([chico, grande])
        eventos, preguntas = [], []
        _instalar_delete(monkeypatch, eventos)
        _instalar_ask(monkeypatch, True, preguntas)

        r = ru.aplicar_politica_al_cargar()

        assert r["accion"] == "fusionado"
        assert r["nodos"] == 2
        assert r["superviviente"] == "Grande"
        assert len(preguntas) == 1
        assert eventos == [("delete", "Chico")]
        fusionado = json.loads(grande.knobs_d["db_json"].value())
        assert fusionado["extra"] == {"nota": "x"}
        assert fusionado["users"]["Mac"]["COMP"] == "/vol/Mac/COMP/"
        assert nuke._estado["nodos"] == [grande]
        assert any("Se fusionaron 2" in m for m in nuke._estado["mensajes"])

    def test_escribe_el_estado_antes_de_borrar(self, monkeypatch):
        chico = _nodo_v2("Chico", db=_db(users={"Mac": {}}))
        grande = _nodo_v2("Grande")
        _escena([grande, chico])
        eventos, preguntas = [], []
        grande.knobs_d["db_json"] = KnobQueRegistra(grande.knobs_d["db_json"].value(), eventos)
        _instalar_delete(monkeypatch, eventos)
        _instalar_ask(monkeypatch, True, preguntas)

        ru.aplicar_politica_al_cargar()

        tipos = [e[0] for e in eventos]
        assert tipos[0] == "write"
        assert "delete" in tipos
        assert tipos.index("write") < tipos.index("delete")

    def test_cancelado_no_borra_nada(self, monkeypatch):
        grande = _nodo_v2("Grande")
        chico = _nodo_v2("Chico", db=_db(users={"Mac": {}}))
        _escena([grande, chico])
        antes = grande.knobs_d["db_json"].value()
        eventos, preguntas = [], []
        _instalar_delete(monkeypatch, eventos)
        _instalar_ask(monkeypatch, False, preguntas)

        r = ru.aplicar_politica_al_cargar()

        assert r["accion"] == "cancelado"
        assert eventos == []
        assert grande.knobs_d["db_json"].value() == antes
        assert len(nuke._estado["nodos"]) == 2
        assert any("No se fusionó nada" in m for m in nuke._estado["mensajes"])

    def test_headless_no_pregunta_ni_borra(self, monkeypatch):
        grande = _nodo_v2("Grande")
        chico = _nodo_v2("Chico", db=_db(users={"Mac": {}}))
        _escena([grande, chico])
        eventos, preguntas = [], []
        _instalar_delete(monkeypatch, eventos)
        _instalar_ask(monkeypatch, True, preguntas)
        monkeypatch.setattr(nuke, "GUI", False, raising=False)

        r = ru.aplicar_politica_al_cargar()

        assert r["accion"] == "headless"
        assert preguntas == []
        assert eventos == []
        assert len(nuke._estado["nodos"]) == 2
        assert any("headless" in m for m in nuke._estado["mensajes"])

    def test_un_viejo_nunca_gana_y_su_estado_se_fusiona(self, monkeypatch):
        viejo = _nodo_viejo("Viejo", rutas={"TO_VFX_SERVER_MAC": "/viejo/TO_VFX/", "comp_SERVER_MAC": "/viejo/COMP/"})
        actual = _nodo_v2("Actual", db=_db(users={"Mac": {"COMP": "/actual/COMP/"}}))
        _escena([viejo, actual])
        eventos, preguntas = [], []
        _instalar_delete(monkeypatch, eventos)
        _instalar_ask(monkeypatch, True, preguntas)

        r = ru.aplicar_politica_al_cargar()

        assert r["accion"] == "fusionado"
        assert r["superviviente"] == "Actual"
        assert eventos == [("delete", "Viejo")]
        fusionado = json.loads(actual.knobs_d["db_json"].value())
        # El viejo aporta su usuario y sus rutas (S9), sin pisar al superviviente.
        assert fusionado["users"]["MacServer"]["TO_VFX"] == "/viejo/TO_VFX/"
        assert fusionado["users"]["Mac"]["COMP"] == "/actual/COMP/"

    def test_solo_nodos_viejos_no_borra_nada(self, monkeypatch):
        uno = _nodo_viejo("Rutas1")
        dos = _nodo_viejo("Rutas2", rutas={"TO_VFX_SERVER_MAC": "/dos/TO_VFX/"})
        _escena([uno, dos])
        eventos, preguntas = [], []
        _instalar_delete(monkeypatch, eventos)
        _instalar_ask(monkeypatch, True, preguntas)

        r = ru.aplicar_politica_al_cargar()

        assert r["accion"] == "error"
        assert eventos == []
        assert len(nuke._estado["nodos"]) == 2
        assert "db_json" not in uno.knobs_d and "db_json" not in dos.knobs_d
        assert any("No se borró nada" in m for m in nuke._estado["mensajes"])

    def test_nunca_lanza_si_el_comp_no_se_puede_leer(self, monkeypatch):
        def explotar():
            raise RuntimeError("comp roto")

        monkeypatch.setattr(nuke, "allNodes", explotar, raising=False)
        r = ru.aplicar_politica_al_cargar()
        # encontrar_nodos_rutas es tolerante: sin lectura no hay nodos, y la
        # política informa "nada" en vez de romper la apertura del script.
        assert r["accion"] == "nada"
        assert r["nodos"] == 0

    def test_tres_nodos_deja_uno_con_todo(self, monkeypatch):
        uno = _nodo_v2("Uno", db=_db(users={"Mac": {"COMP": "/uno/COMP/"}}))
        dos = _nodo_v2(
            "Dos",
            db=_db(
                folders=[
                    {"id": "TO_VFX", "label": "Material Original", "knob": "folder_TO_VFX"},
                    {"id": "COMP", "label": "Composiciones", "knob": "folder_COMP"},
                    {"id": "ASSETS", "label": "Assets", "knob": "folder_ASSETS"},
                ],
                users={
                    "Mac": {"COMP": "/dos/COMP/"},
                    "MacLocal": {"ASSETS": "/local/ASSETS/"},
                },
            ),
        )
        tres = _nodo_v2("Tres", db=_db(users={"Windows": {"COMP": "L:/COMP/"}}))
        _escena([uno, dos, tres])
        eventos, preguntas = [], []
        _instalar_delete(monkeypatch, eventos)
        _instalar_ask(monkeypatch, True, preguntas)

        r = ru.aplicar_politica_al_cargar()

        assert r["accion"] == "fusionado"
        assert r["nodos"] == 3
        assert r["superviviente"] == "Dos"
        assert sorted(e[1] for e in eventos) == ["Tres", "Uno"]
        fusionado = json.loads(dos.knobs_d["db_json"].value())
        assert [f["id"] for f in fusionado["folders"]] == ["TO_VFX", "COMP", "ASSETS"]
        assert set(fusionado["users"]) == {"Mac", "MacLocal", "Windows"}
        assert fusionado["users"]["Windows"]["COMP"] == "L:/COMP/"


# ---------------------------------------------------------------------------
# S4: sincronizar el entorno al abrir el comp (variables PYTHON_*)
# ---------------------------------------------------------------------------


class TestSincronizarEntorno:
    """`sincronizar_entorno`: ejecuta el motor embebido con la acción `sync`."""

    def test_ejecuta_el_motor_embebido_con_sync(self):
        _escena([])
        n = _nodo_v2("Rutas", motor=_codigo_motor())
        assert ru.sincronizar_entorno(n) is True
        assert _llamadas_motor() == ["sync"]

    def test_sin_nodo_devuelve_false(self):
        _escena([])
        assert ru.sincronizar_entorno() is False
        assert _llamadas_motor() == []

    def test_sin_nodo_usa_el_nodo_de_rutas_del_comp(self):
        read = Nodo("Read1", "Read", {"file": Knob("/plano.exr")})
        n = _nodo_v2("Rutas", motor=_codigo_motor())
        _escena([read, n])
        assert ru.sincronizar_entorno() is True
        assert _llamadas_motor() == ["sync"]

    def test_sin_knob_de_motor_devuelve_false(self):
        _escena([])
        n = Nodo("Rutas", "Group", {"db_json": Knob(json.dumps(_db()))})
        assert ru.sincronizar_entorno(n) is False
        assert _llamadas_motor() == []

    def test_motor_vacio_no_cuenta_como_ejecutado(self):
        _escena([])
        n = _nodo_v2("Rutas", motor="   \n")
        assert ru.sincronizar_entorno(n) is False
        assert _llamadas_motor() == []

    def test_motor_sin_entrada_publica_no_cuenta_como_ejecutado(self):
        _escena([])
        assert ru.sincronizar_entorno(_nodo_v2("Rutas", motor="# solo un comentario\n")) is False
        assert _llamadas_motor() == []

    def test_motor_que_lanza_no_propaga_ni_cuenta_como_ejecutado(self):
        _escena([])
        n = _nodo_v2("Rutas", motor=_codigo_motor(falla=True))
        assert ru.sincronizar_entorno(n) is False

    def test_codigo_que_no_compila_no_propaga(self):
        _escena([])
        assert ru.sincronizar_entorno(_nodo_v2("Rutas", motor="def rutas_engine(:\n")) is False

    def test_tolera_nodos_rotos_y_none(self):
        _escena([])
        assert ru.sincronizar_entorno(NodoRoto()) is False
        assert ru.sincronizar_entorno(None) is False


# ---------------------------------------------------------------------------
# S4: proyecto activo para las etiquetas de menú
# ---------------------------------------------------------------------------


class TestProyectoActivo:
    """`proyecto_activo`: estado del nodo, después root.name(), después "Proyecto"."""

    def test_usa_la_ruta_comp_del_usuario_activo(self):
        n = _nodo_v2(
            "Rutas",
            db=_db(active="Linux", users={"Linux": {"COMP": "/mnt/wupm/2026/HTLR/COMP/EP_107/"}}),
        )
        _escena([n])
        nuke._estado["root_name"] = "/otro/lugar/OTRO/COMP/EP_1/x_001_010_00100.nk"
        assert ru.proyecto_activo() == "HTLR"

    def test_lee_el_estado_del_superviviente(self):
        chico = _nodo_v2("Chico", db=_db(users={"Mac": {}}))
        grande = _nodo_v2(
            "Grande",
            db=_db(
                users={
                    "Mac": {"COMP": "/Volumes/wupm/2026/PCF/COMP/"},
                    "Linux": {"COMP": "/mnt/wupm/2026/PCF/COMP/"},
                }
            ),
        )
        _escena([chico, grande])
        nuke._estado["root_name"] = ""
        assert ru.proyecto_activo() == "PCF"

    def test_active_user_invalido_usa_un_usuario_del_estado(self):
        n = _nodo_v2(
            "Rutas",
            db=_db(
                active="Fantasma",
                users={"Mac": {"COMP": "/Volumes/wupm/2026/HTLR/COMP/"}},
            ),
        )
        _escena([n])
        nuke._estado["root_name"] = ""
        assert ru.proyecto_activo() == "HTLR"

    def test_cae_al_nombre_del_root_si_el_estado_no_tiene_comp(self):
        n = _nodo_v2("Rutas", db=_db(users={"Mac": {"COMP": ""}}))
        _escena([n])
        nuke._estado["root_name"] = (
            "/Volumes/wupm/2026/PCF/COMP/EP_001/PCF_001_010_00100_comp_SAMAN_V01.nk"
        )
        assert ru.proyecto_activo() == "PCF"

    def test_sin_estado_ni_root_cae_al_nombre_por_defecto(self):
        _escena([])
        nuke._estado["root_name"] = ""
        assert ru.proyecto_activo() == "Proyecto"

    def test_nunca_lanza_y_siempre_devuelve_str(self):
        _escena([NodoRoto()])
        nuke._estado["root_name"] = ""
        proyecto = ru.proyecto_activo()
        assert isinstance(proyecto, str)
        assert proyecto == "Proyecto"


# ---------------------------------------------------------------------------
# S3, S4: la sincronización viaja con el hook de carga
# ---------------------------------------------------------------------------


class TestSincronizacionAlCargar:
    """El hook empuja el entorno sólo cuando deja un nodo vivo en el comp."""

    def test_sincroniza_con_un_nodo(self):
        n = _nodo_v2("Rutas", motor=_codigo_motor())
        _escena([n])
        r = ru.aplicar_politica_al_cargar()
        assert r["accion"] == "unico"
        assert _llamadas_motor() == ["sync"]

    def test_sincroniza_al_fusionar_despues_de_escribir_el_estado(self, monkeypatch):
        chico = _nodo_v2("Chico", db=_db(users={"Mac": {}}))
        grande = _nodo_v2("Grande", motor=_codigo_motor())
        grande.knobs_d["db_json"] = KnobQueEscribeEnElMotor(
            grande.knobs_d["db_json"].value()
        )
        _escena([chico, grande])
        _instalar_delete(monkeypatch, [])
        _instalar_ask(monkeypatch, True, [])

        r = ru.aplicar_politica_al_cargar()

        assert r["accion"] == "fusionado"
        assert r["superviviente"] == "Grande"
        assert _llamadas_motor() == ["write", "sync"]
        assert nuke._estado["nodos"] == [grande]

    def test_no_sincroniza_sin_nodos(self):
        _escena([])
        r = ru.aplicar_politica_al_cargar()
        assert r["accion"] == "nada"
        assert _llamadas_motor() == []

    def test_no_sincroniza_si_se_cancela(self, monkeypatch):
        grande = _nodo_v2("Grande", motor=_codigo_motor())
        chico = _nodo_v2("Chico", db=_db(users={"Mac": {}}))
        _escena([grande, chico])
        _instalar_delete(monkeypatch, [])
        _instalar_ask(monkeypatch, False, [])

        r = ru.aplicar_politica_al_cargar()

        assert r["accion"] == "cancelado"
        assert _llamadas_motor() == []

    def test_no_sincroniza_en_headless(self, monkeypatch):
        grande = _nodo_v2("Grande", motor=_codigo_motor())
        chico = _nodo_v2("Chico", db=_db(users={"Mac": {}}))
        _escena([grande, chico])
        _instalar_delete(monkeypatch, [])
        _instalar_ask(monkeypatch, True, [])
        monkeypatch.setattr(nuke, "GUI", False, raising=False)

        r = ru.aplicar_politica_al_cargar()

        assert r["accion"] == "headless"
        assert _llamadas_motor() == []

    def test_no_sincroniza_cuando_no_hay_donde_escribir(self, monkeypatch):
        uno = _nodo_viejo("Rutas1", Cerebro_Python=_codigo_motor())
        dos = _nodo_viejo(
            "Rutas2", rutas={"TO_VFX_SERVER_MAC": "/dos/TO_VFX/"}, Cerebro_Python=_codigo_motor()
        )
        _escena([uno, dos])
        _instalar_delete(monkeypatch, [])
        _instalar_ask(monkeypatch, True, [])

        r = ru.aplicar_politica_al_cargar()

        assert r["accion"] == "error"
        assert _llamadas_motor() == []

    def test_un_motor_roto_no_rompe_el_hook(self):
        n = _nodo_v2("Rutas", motor=_codigo_motor(falla=True))
        _escena([n])
        r = ru.aplicar_politica_al_cargar()
        assert r["accion"] == "unico"
        assert set(r) == {"accion", "nodos", "superviviente", "detalle"}


# ---------------------------------------------------------------------------
# S4, S11: acción explícita de menú (crear / reutilizar / actualizar)
# ---------------------------------------------------------------------------


class TestCrearOActualizar:
    """
    Ramas de `crear_o_actualizar`: 0 nodos, 1 actual, 1 viejo (sí/no/headless),
    2+ (delegación en la fusión) y el error del nodo pegado inutilizable.
    """

    def test_sin_nodos_pega_el_gizmo_y_marca_la_version(self, monkeypatch):
        _escena([])
        nuevo = Nodo("Rutas", "Group", {"db_json": Knob(json.dumps(_db()))})
        antes = nuevo.knobs_d["db_json"].value()
        pastes = []
        _instalar_paste(monkeypatch, lambda ruta: nuevo, pastes)
        eventos = []
        _instalar_delete(monkeypatch, eventos)
        monkeypatch.setattr(
            nuke,
            "Int_Knob",
            lambda nombre, etiqueta="": KnobConNombre(nombre, etiqueta),
            raising=False,
        )

        r = ru.crear_o_actualizar()

        assert r["accion"] == "creado"
        assert r["nodos"] == 1
        assert r["superviviente"] == "Rutas"
        assert len(pastes) == 1
        assert pastes[0].endswith(os.path.join("SamanTools", "nodos", "Rutas.gizmo"))
        # El gizmo pegado queda marcado como versión actual...
        assert ru.es_version_actual(nuevo) is True
        # ...sin reescribir su estado (crear no escribe estado).
        assert nuevo.knobs_d["db_json"].value() == antes
        assert nuke._estado["nodos"] == [nuevo]
        assert eventos == []          # crear no borra nada
        assert nuevo.enfocado == 1    # selecciona y enfoca

    def test_sin_nodos_acepta_la_ruta_del_gizmo(self, monkeypatch):
        _escena([])
        nuevo = _nodo_v2("Rutas")
        pastes = []
        _instalar_paste(monkeypatch, lambda ruta: nuevo, pastes)

        r = ru.crear_o_actualizar("/otro/lugar/Rutas.gizmo")

        assert r["accion"] == "creado"
        assert pastes == ["/otro/lugar/Rutas.gizmo"]

    def test_un_nodo_actual_se_reutiliza_sin_pegar(self, monkeypatch):
        actual = _nodo_v2("Actual")
        _escena([actual])
        antes = actual.knobs_d["db_json"].value()
        pastes, preguntas = [], []
        _instalar_paste(monkeypatch, lambda ruta: _nodo_v2("Pegado"), pastes)
        _instalar_ask(monkeypatch, True, preguntas)
        eventos = []
        _instalar_delete(monkeypatch, eventos)

        r = ru.crear_o_actualizar()

        assert r["accion"] == "unico"
        assert r["nodos"] == 1
        assert r["superviviente"] == "Actual"
        assert pastes == [] and preguntas == []
        # El unico borrado es el nodo descartable que se crea para leer el cursor
        # (S15); el nodo real del comp no se toca.
        assert len(eventos) == 1, "solo se borra el descartable del cursor"
        assert all(nombre != "Actual" for (_, nombre) in eventos)
        assert actual.knobs_d["db_json"].value() == antes
        assert actual.enfocado == 1

    def test_un_nodo_viejo_se_actualiza_conservando_estado_y_posicion(self, monkeypatch):
        viejo = _nodo_viejo("Rutas1", string="PALF")
        viejo.posxy = (120, -340)
        _escena([viejo])
        nuevo = _nodo_v2("Rutas")
        pastes, preguntas = [], []
        _instalar_paste(monkeypatch, lambda ruta: nuevo, pastes)
        _instalar_ask(monkeypatch, True, preguntas)
        eventos = []
        _instalar_delete(monkeypatch, eventos)

        r = ru.crear_o_actualizar()

        assert r["accion"] == "actualizado"
        assert r["nodos"] == 1
        assert r["superviviente"] == "Rutas"
        assert len(preguntas) == 1
        assert len(pastes) == 1
        assert eventos == [("delete", "Rutas1")]
        assert nuevo.posxy == (120, -340)
        assert nuevo.enfocado == 1
        db = json.loads(nuevo.knobs_d["db_json"].value())
        assert db["active_user"] == "MacServer"
        assert db["users"]["MacServer"]["TO_VFX"] == "/vol/TO_VFX/"
        assert db["legacy_knobs"]["string"] == "PALF"
        assert nuke._estado["nodos"] == [nuevo]

    def test_escribe_estado_y_posicion_antes_de_borrar_el_viejo(self, monkeypatch):
        viejo = _nodo_viejo("Rutas1")
        viejo.posxy = (10, 20)
        _escena([viejo])
        eventos = []
        nuevo = _nodo_v2("Rutas")
        nuevo.knobs_d["db_json"] = KnobQueRegistra(
            nuevo.knobs_d["db_json"].value(), eventos
        )

        def pegar(ruta):
            eventos.append(("paste", ruta))
            return nuevo

        def borrar(nodo):
            # El nodo viejo sólo se borra con el estado y la posición ya puestos.
            eventos.append(("delete", nodo.name(), nuevo.posxy))
            nuke._estado["nodos"] = [n for n in nuke._estado["nodos"] if n is not nodo]

        monkeypatch.setattr(nuke, "delete", borrar, raising=False)
        _instalar_paste(monkeypatch, pegar, [])
        _instalar_ask(monkeypatch, True, [])

        r = ru.crear_o_actualizar()

        assert r["accion"] == "actualizado"
        assert [e[0] for e in eventos] == ["paste", "write", "delete"]
        assert eventos[2] == ("delete", "Rutas1", (10, 20))

    def test_cancelado_no_pega_ni_borra(self, monkeypatch):
        viejo = _nodo_viejo("Rutas1")
        _escena([viejo])
        pastes, preguntas = [], []
        _instalar_paste(monkeypatch, lambda ruta: _nodo_v2("Pegado"), pastes)
        _instalar_ask(monkeypatch, False, preguntas)
        eventos = []
        _instalar_delete(monkeypatch, eventos)

        r = ru.crear_o_actualizar()

        assert r["accion"] == "cancelado"
        assert r["nodos"] == 1
        assert r["superviviente"] == "Rutas1"
        assert pastes == [] and eventos == []
        assert nuke._estado["nodos"] == [viejo]
        assert any("No se actualizó" in m for m in nuke._estado["mensajes"])

    def test_headless_no_pregunta_ni_pega_ni_borra(self, monkeypatch):
        viejo = _nodo_viejo("Rutas1")
        _escena([viejo])
        pastes, preguntas = [], []
        _instalar_paste(monkeypatch, lambda ruta: _nodo_v2("Pegado"), pastes)
        _instalar_ask(monkeypatch, True, preguntas)
        eventos = []
        _instalar_delete(monkeypatch, eventos)
        monkeypatch.setattr(nuke, "GUI", False, raising=False)

        r = ru.crear_o_actualizar()

        assert r["accion"] == "headless"
        assert r["superviviente"] == "Rutas1"
        assert preguntas == [] and pastes == [] and eventos == []
        assert nuke._estado["nodos"] == [viejo]
        assert any("headless" in m for m in nuke._estado["mensajes"])

    def test_con_dos_nodos_delega_en_la_fusion(self, monkeypatch):
        viejo = _nodo_viejo("Viejo")
        actual = _nodo_v2("Actual", db=_db(users={"Mac": {"COMP": "/actual/COMP/"}}))
        _escena([viejo, actual])
        pastes, preguntas = [], []
        _instalar_paste(monkeypatch, lambda ruta: _nodo_v2("Pegado"), pastes)
        _instalar_ask(monkeypatch, True, preguntas)
        eventos = []
        _instalar_delete(monkeypatch, eventos)

        r = ru.crear_o_actualizar()

        assert r["accion"] == "fusionado"
        assert r["nodos"] == 2
        assert r["superviviente"] == "Actual"
        assert len(preguntas) == 1
        assert eventos == [("delete", "Viejo")]
        assert pastes == []   # la fusión no pega nada
        fusionado = json.loads(actual.knobs_d["db_json"].value())
        assert fusionado["users"]["MacServer"]["TO_VFX"] == "/vol/TO_VFX/"

    def test_si_el_nodo_nuevo_no_puede_guardar_estado_conserva_el_viejo(self, monkeypatch):
        viejo = _nodo_viejo("Rutas1")
        _escena([viejo])
        # El pegado no es el gizmo esperado: no tiene db_json.
        nuevo = Nodo("Rutas", "Group", {"file": Knob("")})
        pastes, preguntas = [], []
        _instalar_paste(monkeypatch, lambda ruta: nuevo, pastes)
        _instalar_ask(monkeypatch, True, preguntas)
        eventos = []
        _instalar_delete(monkeypatch, eventos)

        r = ru.crear_o_actualizar()

        assert r["accion"] == "error"
        assert r["superviviente"] == "Rutas1"
        # Sólo se descarta el nodo recién pegado; el viejo sigue ahí.
        assert eventos == [("delete", "Rutas")]
        assert nuke._estado["nodos"] == [viejo]

    def test_devuelve_la_forma_exacta_del_informe(self, monkeypatch):
        _escena([])
        _instalar_paste(monkeypatch, lambda ruta: _nodo_v2("Rutas"), [])
        r = ru.crear_o_actualizar("/x/Rutas.gizmo")
        assert set(r) == {"accion", "nodos", "superviviente", "detalle"}
        assert isinstance(r["nodos"], int)
        assert isinstance(r["detalle"], str)

    def test_el_modulo_no_importa_nuke_al_tope(self):
        with open(ru.__file__, encoding="utf-8") as f:
            for linea in f:
                assert not linea.startswith("import nuke")
                assert not linea.startswith("from nuke ")


class TestNodoBajoElCursor:
    """S15: si el nodo ya existe, aparece bajo el cursor como un nodo nuevo."""

    def _preparar(self, monkeypatch, cursor=(4321, 8765)):
        actual = _nodo_v2("Actual")
        actual.setXYpos(900, 900)
        _escena([actual])
        nuke._estado.pop("centro_vista", None)
        pastes, preguntas = [], []
        _instalar_paste(monkeypatch, lambda ruta: _nodo_v2("Pegado"), pastes)
        _instalar_ask(monkeypatch, True, preguntas)
        eventos = []
        _instalar_delete(monkeypatch, eventos)
        nuke._estado["zoom_to_fit"] = []
        descartables = []

        def _crear(*a, **k):
            if cursor is None:
                raise RuntimeError("sin DAG")
            nodo = _nodo_v2("Descartable")
            nodo.setXYpos(*cursor)
            descartables.append(nodo)
            return nodo

        monkeypatch.setattr(nuke, "createNode", _crear, raising=False)
        return actual, pastes, preguntas, eventos, descartables

    def test_aparece_bajo_el_cursor_como_un_nodo_nuevo(self, monkeypatch):
        actual, pastes, preguntas, eventos, descartables = self._preparar(monkeypatch)

        r = ru.crear_o_actualizar()

        assert r["accion"] == "unico"
        assert (actual.xpos(), actual.ypos()) == (4321, 8765), (
            "el nodo se mueve a donde nace un nodo nuevo: el cursor"
        )
        assert nuke._estado["zoom_to_fit"] == [], "no se debe mover la vista"
        assert pastes == [] and preguntas == []
        assert actual.enfocado == 1, "el panel del nodo se abre igual"
        assert len(descartables) == 1, "se crea UN nodo descartable para leer el cursor"
        assert ("delete", "Descartable") in eventos, "el descartable se borra siempre"
        assert all(n is not descartables[0] for n in nuke._estado["nodos"])

    def test_sin_cursor_cae_al_centro_de_la_vista(self, monkeypatch):
        actual, __, ___, ____, _____ = self._preparar(monkeypatch, cursor=None)
        nuke._estado["centro_vista"] = [1200, -340]

        ru.crear_o_actualizar()

        assert (actual.xpos(), actual.ypos()) == (1200, -340)

    def test_sin_cursor_ni_centro_conserva_la_posicion(self, monkeypatch):
        actual = self._preparar(monkeypatch, cursor=None)[0]
        nuke._estado["centro_vista"] = []

        ru.crear_o_actualizar()

        assert (actual.xpos(), actual.ypos()) == (900, 900)

    def test_en_headless_no_mueve_el_nodo(self, monkeypatch):
        actual = self._preparar(monkeypatch)[0]
        monkeypatch.setattr(ru, "_en_headless", lambda: True)

        ru.crear_o_actualizar()

        assert (actual.xpos(), actual.ypos()) == (900, 900)
