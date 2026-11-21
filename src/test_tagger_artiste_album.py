#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""Jeu de tests : gestion du tag « Artiste de l'album » (TPE2) du tagger.

Ce fichier fabrique lui-même tout ce dont il a besoin :
  - de faux fichiers MP3 (quelques trames silencieuses + des tags ID3) ;
  - de fausses réponses Discogs (aucun réseau, aucun token nécessaire).
Il ne touche à aucun de vos vrais fichiers : tout se passe dans un dossier
temporaire supprimé à la fin de chaque test.

Lancement (depuis le dossier qui contient ce fichier) :
    python test_tagger_artiste_album.py -v

Où sont cherchés tagger.py et tagger_gui.py ? Dans l'ordre :
  1. variables d'environnement TAGGER_PATH / TAGGER_GUI_PATH (si définies) ;
  2. le dossier de ce fichier, puis ses sous-dossiers src/ et src/gui/ ;
  3. le dossier parent et ../src, ../src/gui.

Comment lire le résultat
------------------------
  ok                   : le comportement attendu est bien là ;
  expected failure     : correction PAS ENCORE faite (normal pour l'instant) ;
  unexpected success   : une correction « à venir » fonctionne désormais !
                         --> retirez alors la ligne « @unittest.expectedFailure »
                             du test concerné : il devient un test normal ;
  FAIL / ERROR         : régression, à regarder en priorité.

Les trois groupes de tests :
  - TestCorrectionsV256   : ce qui est déjà corrigé en V2.5.6 (doit être « ok »)
  - TestCorrectionsAVenir : ce qui reste à corriger (« expected failure » pour l'instant)
  - TestInterfaceGraphique: la fenêtre Qt (ignoré si PyQt6 n'est pas installé)

IMPORTANT : les tests « à venir » reposent sur des hypothèses de comportement
(par ex. « A & B » pour deux artistes). Elles sont écrites dans la docstring de
chaque test : modifiez-les si votre choix est différent.
"""

import contextlib
import copy
import importlib.util
import io
import logging
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

from mutagen.id3 import COMM, ID3, TPE2, TRCK, TXXX

HERE = os.path.dirname(os.path.abspath(__file__))

# Evite que tagger.py (appels logging.debug/info...) installe un affichage par défaut :
# on garde la sortie des tests lisible.
logging.getLogger().addHandler(logging.NullHandler())


# ---------------------------------------------------------------------------
# Chargement des scripts à tester
# ---------------------------------------------------------------------------
def _find_script(env_var: str, filename: str) -> str:
    candidates = []
    if os.environ.get(env_var):
        candidates.append(os.environ[env_var])
    for rel in (
        ".",
        "src",
        os.path.join("src", "gui"),
        "gui",
        "..",
        os.path.join("..", "src"),
        os.path.join("..", "src", "gui"),
    ):
        candidates.append(os.path.join(HERE, rel, filename))
    for path in candidates:
        if os.path.isfile(path):
            return os.path.abspath(path)
    raise FileNotFoundError(
        f"{filename} introuvable. Définissez la variable d'environnement {env_var}."
    )


def _load_module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TAGGER_PATH = _find_script("TAGGER_PATH", "tagger.py")
tg = _load_module("tagger_under_test", TAGGER_PATH)


# ---------------------------------------------------------------------------
# JEU DE DONNÉES : fausses releases Discogs
# ---------------------------------------------------------------------------
def make_release(artists, titles=("Piste 1", "Piste 2"), track_artists=None):
    """Construit une fausse release Discogs (2 pistes par défaut).

    Attention : pas de clé « images » (tagger.py ne gère pas une liste vide).
    NB : le format des artistes par piste (« artists » dans la tracklist) est à
    confirmer sur un vrai JSON Discogs avant de coder la correction « compilation ».
    """
    tracklist = []
    for i, titre in enumerate(titles, 1):
        item = {
            "type_": "track",
            "position": str(i),
            "title": titre,
            "duration": "3:00",
        }
        if track_artists:
            item["artists"] = [{"name": track_artists[i - 1]}]
        tracklist.append(item)
    return {
        "artists": artists,
        "title": "Album Test",
        "year": 1999,
        "uri": "https://www.discogs.com/release/1",
        "genres": ["Pop"],
        "styles": [],
        "tracklist": tracklist,
    }


RELEASES = {
    # 1. Un artiste simple
    "simple": make_release([{"name": "Madonna", "join": ""}]),
    # 2. Deux artistes (« & » = mot de liaison Discogs)
    "deux_artistes": make_release(
        [
            {"name": "Alain Souchon", "join": "&"},
            {"name": "Laurent Voulzy", "join": ""},
        ]
    ),
    # 3. Une compilation (artiste Discogs « Various », artiste différent par piste)
    "compilation": make_release(
        [{"name": "Various", "join": ""}],
        track_artists=["Artiste Un", "Artiste Deux"],
    ),
    # 4. Un nom avec le suffixe Discogs « (2) »
    "suffixe_2": make_release([{"name": "Sublime (2)", "join": ""}]),
    # 5. Noms avec Œ/œ et apostrophe typographique ’
    "oe": make_release([{"name": "Cœur de Pirate", "join": ""}]),
    "apostrophe": make_release([{"name": "Guns N’ Roses", "join": ""}]),
}

# Releases dont l'artiste est impossible à déterminer
RELEASES_SANS_ARTISTE = {
    "cle_absente": {"title": "X", "tracklist": []},
    "liste_vide": {"artists": [], "title": "X", "tracklist": []},
    "nom_none": {"artists": [{"name": None}], "title": "X", "tracklist": []},
    "nom_vide": {"artists": [{"name": "   "}], "title": "X", "tracklist": []},
    "element_invalide": {"artists": ["x"], "title": "X", "tracklist": []},
}


# ---------------------------------------------------------------------------
# Outils : faux MP3, faux Discogs, exécution de main()
# ---------------------------------------------------------------------------
# Une trame MP3 silencieuse (MPEG-1 Layer III, 128 kbit/s, 44,1 kHz)
SILENT_FRAME = b"\xff\xfb\x90\x00" + b"\x00" * 413


def make_mp3(path, track=None, frames=()):
    """Crée un faux MP3 avec un numéro de piste et d'éventuels tags ID3."""
    with open(path, "wb") as fh:
        fh.write(SILENT_FRAME * 10)
    tags = ID3()
    if track is not None:
        tags.add(TRCK(encoding=3, text=str(track)))
    for frame in frames:
        tags.add(frame)
    tags.save(path)


@contextlib.contextmanager
def capture_logs():
    """Récupère les messages de log sous forme de liste [(NIVEAU, message)]."""
    records = []

    class _Handler(logging.Handler):
        def emit(self, record):
            records.append((record.levelname, record.getMessage()))

    handler = _Handler(level=logging.DEBUG)
    root = logging.getLogger()
    old_level = root.level
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    try:
        yield records
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)


class _FakeResponse:
    status_code = 200
    url = "fake://discogs"
    content = b""

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class Resultat:
    """Ce que main() a produit : code de sortie, dossiers créés, tags relus."""

    def __init__(self):
        self.exit_code = None
        self.dossiers = []  # dossiers présents à côté du dossier « MP3 »
        self.tags = {}  # {"01.mp3": ID3, ...} relus dans le dossier MP3
        self.logs = []  # [(niveau, message)]

    def frame(self, nom_fichier, cle):
        """Valeur texte d'une frame (ex. 'TPE2'), ou None si absente."""
        tags = self.tags[nom_fichier]
        return str(tags[cle]) if cle in tags else None


def run_main(release, interprete="default", album_artist="default", prepare=None):
    """Exécute tagger.main() de bout en bout sur de faux MP3 et un faux Discogs.

    prepare : fonction facultative prepare(liste_des_chemins) appelée avant
              l'exécution, pour ajouter des tags existants aux faux MP3.
    """
    res = Resultat()
    with tempfile.TemporaryDirectory() as tmp:
        folder = os.path.join(tmp, "MP3")
        os.makedirs(folder)
        paths = []
        for n in range(1, len(release["tracklist"]) + 1):
            path = os.path.join(folder, f"{n:02d}.mp3")
            make_mp3(path, track=n)
            paths.append(path)
        if prepare:
            prepare(paths)

        def fake_get(url, **kwargs):
            if "database/search" in url:
                return _FakeResponse(
                    {"results": [{"resource_url": "https://api.discogs.com/releases/1"}]}
                )
            return _FakeResponse(copy.deepcopy(release))

        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.multiple(
                    tg,
                    create=True,
                    BARCODE="123",
                    AUDIO_FOLDER=folder,
                    GENRE="default",
                    RELEASE_ID="default",
                    INTERPRETE=interprete,
                    ALBUM_FORCE="default",
                    ALBUM_ARTIST_FORCE=album_artist,
                    DISCOGS_TOKEN="test",
                    args=types.SimpleNamespace(compositeur=False),
                    audio_files=tg.get_audio_files(folder),
                )
            )
            stack.enter_context(mock.patch.object(tg.requests, "get", side_effect=fake_get))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            logs = stack.enter_context(capture_logs())
            try:
                tg.main()
                res.exit_code = 0
            except SystemExit as exc:
                res.exit_code = 0 if exc.code in (None, 0) else exc.code
        res.logs = list(logs)

        res.dossiers = sorted(os.listdir(tmp))
        for nom in sorted(os.listdir(folder)):
            if nom.lower().endswith(".mp3"):
                try:
                    res.tags[nom] = ID3(os.path.join(folder, nom))
                except Exception:
                    res.tags[nom] = ID3()  # fichier sans tag
    return res


# ===========================================================================
# GROUPE 1 : ce qui est déjà corrigé en V2.5.6 (ces tests doivent être « ok »)
# ===========================================================================
class TestCorrectionsV256(unittest.TestCase):

    # --- compute_artists() : fonction unique de calcul -----------------------
    def test_01_artiste_simple(self):
        """Artiste simple : artiste du morceau = artiste de l'album = nom Discogs."""
        self.assertEqual(
            tg.compute_artists(RELEASES["simple"]), ("Madonna", "Madonna")
        )

    def test_02_option_interprete(self):
        """Option -i : remplace l'artiste, et l'artiste de l'album suit par défaut."""
        self.assertEqual(
            tg.compute_artists(RELEASES["simple"], "Michel Jonasz"),
            ("Michel Jonasz", "Michel Jonasz"),
        )

    def test_03_option_artiste_album(self):
        """Option -A : change SEULEMENT l'artiste de l'album."""
        self.assertEqual(
            tg.compute_artists(RELEASES["simple"], "default", "Orchestre National"),
            ("Madonna", "Orchestre National"),
        )

    def test_04_interprete_et_artiste_album(self):
        """Options -i et -A ensemble : deux valeurs indépendantes."""
        self.assertEqual(
            tg.compute_artists(RELEASES["simple"], "Soliste", "Orchestre"),
            ("Soliste", "Orchestre"),
        )

    def test_05_options_vides_ignorees(self):
        """Options -i / -A vides ou faites d'espaces : ignorées (avec avertissement)."""
        with capture_logs() as logs:
            resultat = tg.compute_artists(RELEASES["simple"], "", "   ")
        self.assertEqual(resultat, ("Madonna", "Madonna"))
        warnings = [m for niveau, m in logs if niveau == "WARNING"]
        self.assertEqual(len(warnings), 2, warnings)

    def test_06_artiste_introuvable_erreur_claire(self):
        """Pas d'artiste (clé absente, liste vide, None, vide...) : erreur claire."""
        for nom, release in RELEASES_SANS_ARTISTE.items():
            with self.subTest(cas=nom):
                with capture_logs():
                    with self.assertRaises(ValueError) as ctx:
                        tg.compute_artists(release)
                self.assertIn("-i", str(ctx.exception))  # le message indique la solution

    def test_07_artiste_introuvable_mais_interprete_fourni(self):
        """Pas d'artiste Discogs mais -i fourni : on continue avec -i."""
        with capture_logs():
            self.assertEqual(
                tg.compute_artists(RELEASES_SANS_ARTISTE["liste_vide"], "Dupont"),
                ("Dupont", "Dupont"),
            )

    def test_08_release_inutilisable(self):
        """Release None ou non-dictionnaire : erreur claire, pas de plantage obscur."""
        for valeur in (None, [], "texte"):
            with self.subTest(valeur=valeur):
                with capture_logs():
                    with self.assertRaises(ValueError):
                        tg.compute_artists(valeur)

    # --- ligne de commande ---------------------------------------------------
    def test_09_ligne_de_commande(self):
        """-A / --artiste_album est reconnue ; sans l'option la valeur est « default »."""
        with mock.patch.object(sys, "argv", ["tagger.py", "123", "-A", "Orchestre X"]):
            self.assertEqual(tg.cmdline_args().ALBUM_ARTIST_FORCE, "Orchestre X")
        with mock.patch.object(
            sys, "argv", ["tagger.py", "123", "--artiste_album", "Choeur Y"]
        ):
            self.assertEqual(tg.cmdline_args().ALBUM_ARTIST_FORCE, "Choeur Y")
        with mock.patch.object(sys, "argv", ["tagger.py", "123"]):
            self.assertEqual(tg.cmdline_args().ALBUM_ARTIST_FORCE, "default")

    def test_10_option_album_inchangee(self):
        """L'ancienne option -a (titre) fonctionne toujours (pas de conflit avec -A)."""
        with mock.patch.object(
            sys, "argv", ["tagger.py", "123", "-a", "Mon titre", "-A", "Orchestre"]
        ):
            args = tg.cmdline_args()
        self.assertEqual(args.ALBUM_FORCE, "Mon titre")
        self.assertEqual(args.ALBUM_ARTIST_FORCE, "Orchestre")

    # --- préparation et écriture des tags -----------------------------------
    def test_11_prepare_new_tags_deux_valeurs(self):
        """prepare_new_tags() : « artist » et « albumartist » peuvent différer."""
        with mock.patch.multiple(tg, create=True, GENRE="default", BARCODE="123"):
            tags = tg.prepare_new_tags(
                RELEASES["simple"], 1, 2, "Soliste", "Album", {1: "T1"}, {1: ""}, "Orchestre"
            )
            self.assertEqual((tags["artist"], tags["albumartist"]), ("Soliste", "Orchestre"))
            # Ancien appel (sans le nouveau paramètre) : comportement d'avant conservé
            tags = tg.prepare_new_tags(
                RELEASES["simple"], 1, 2, "Soliste", "Album", {1: "T1"}, {1: ""}
            )
            self.assertEqual((tags["artist"], tags["albumartist"]), ("Soliste", "Soliste"))

    def test_12_ecriture_dans_le_fichier(self):
        """apply_tags() : TPE1 et TPE2 réellement différents dans le fichier MP3."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "01.mp3")
            make_mp3(path, track=1)
            with mock.patch.multiple(tg, create=True, GENRE="default", BARCODE="123"):
                tags = tg.prepare_new_tags(
                    RELEASES["simple"], 1, 2, "Soliste", "Album", {1: "T1"}, {1: ""}, "Orchestre"
                )
            tg.apply_tags(path, tags)
            relu = ID3(path)
        self.assertEqual(str(relu["TPE1"]), "Soliste")
        self.assertEqual(str(relu["TPE2"]), "Orchestre")

    # --- main() de bout en bout ---------------------------------------------
    def test_13_main_options_et_dossier(self):
        """main() : tags TPE1/TPE2 distincts ; le dossier suit l'artiste de l'album."""
        res = run_main(RELEASES["simple"], "Soliste Y", "Orchestre/Choeur X")
        self.assertEqual(res.exit_code, 0)
        self.assertEqual(res.frame("01.mp3", "TPE1"), "Soliste Y")
        self.assertEqual(res.frame("01.mp3", "TPE2"), "Orchestre/Choeur X")  # « / » gardé dans le tag
        self.assertIn("Orchestre-Choeur X -- Album Test", res.dossiers)  # « / » remplacé dans le dossier

    def test_14_main_sans_options_comportement_inchange(self):
        """main() sans -i ni -A : artiste = artiste de l'album = nom Discogs (comme avant)."""
        res = run_main(RELEASES["simple"])
        self.assertEqual(res.exit_code, 0)
        for nom in ("01.mp3", "02.mp3"):
            self.assertEqual(res.frame(nom, "TPE1"), "Madonna")
            self.assertEqual(res.frame(nom, "TPE2"), "Madonna")
        self.assertIn("Madonna -- Album Test", res.dossiers)

    def test_15_main_artiste_introuvable_aucun_tag_modifie(self):
        """main() sans artiste : arrêt (code 1) AVANT toute modification de tags."""
        res = run_main(make_release([]))  # release avec 2 pistes mais sans aucun artiste
        self.assertEqual(res.exit_code, 1)
        self.assertNotIn("TPE1", res.tags["01.mp3"])
        self.assertNotIn("TPE2", res.tags["01.mp3"])
        self.assertEqual(res.dossiers, ["MP3"])  # aucun dossier final créé
        erreurs = [m for niveau, m in res.logs if niveau == "ERROR"]
        self.assertTrue(any("-i" in m for m in erreurs), erreurs)

    # --- TPE2 déjà présent dans le fichier -----------------------------------
    @staticmethod
    def _avec_tpe2_existant(paths):
        for path in paths:
            tags = ID3(path)
            tags.add(TPE2(encoding=3, text="Saisi à la main"))
            tags.save(path)

    def test_16_tpe2_existant_remplace_par_la_valeur_calculee(self):
        """Fichier ayant déjà un TPE2, sans -A : remplacé par la valeur calculée.
        (Comportement actuel, à conserver tant qu'aucune option « conserver » n'existe.)"""
        res = run_main(RELEASES["simple"], prepare=self._avec_tpe2_existant)
        self.assertEqual(res.frame("01.mp3", "TPE2"), "Madonna")

    def test_17_tpe2_existant_et_option_A(self):
        """Fichier ayant déjà un TPE2, avec -A : la valeur de -A l'emporte."""
        res = run_main(
            RELEASES["simple"], album_artist="Orchestre National", prepare=self._avec_tpe2_existant
        )
        self.assertEqual(res.frame("01.mp3", "TPE2"), "Orchestre National")

    # --- contrôle / alertes --------------------------------------------------
    def test_18_tableau_alertes(self):
        """Tableau final : alerte si TPE2 vide/absent ou différent selon les pistes."""
        with tempfile.TemporaryDirectory() as tmp:
            valeurs = {1: "Artiste A", 2: "Artiste B", 3: ""}
            for n, valeur in valeurs.items():
                make_mp3(
                    os.path.join(tmp, f"{n:02d}.mp3"),
                    track=n,
                    frames=[TPE2(encoding=3, text=valeur)],
                )
            with contextlib.redirect_stdout(io.StringIO()) as sortie, capture_logs() as logs:
                tg.afficher_infos_album_tabulate(tmp)
        self.assertIn("Artiste album", sortie.getvalue())  # nouvelle colonne
        self.assertIn("(vide)", sortie.getvalue())
        alertes = [m for niveau, m in logs if niveau == "WARNING"]
        self.assertTrue(any("vide ou absent" in m for m in alertes), alertes)
        self.assertTrue(any("different selon les pistes" in m for m in alertes), alertes)

    def test_19_tableau_coherent(self):
        """Tableau final : message d'information (et aucune alerte) si tout est cohérent."""
        with tempfile.TemporaryDirectory() as tmp:
            for n in (1, 2):
                make_mp3(
                    os.path.join(tmp, f"{n:02d}.mp3"),
                    track=n,
                    frames=[TPE2(encoding=3, text="Orchestre National")],
                )
            with contextlib.redirect_stdout(io.StringIO()), capture_logs() as logs:
                tg.afficher_infos_album_tabulate(tmp)
        self.assertEqual([m for niveau, m in logs if niveau == "WARNING"], [])
        self.assertTrue(any("coherent" in m for niveau, m in logs if niveau == "INFO"))


# ===========================================================================
# GROUPE 2 : corrections À VENIR (« expected failure » tant qu'elles ne sont pas faites)
# Ces tests passent par main() : ils ne dépendent donc pas du nom des futures fonctions.
# ===========================================================================
class TestCorrectionsAVenir(unittest.TestCase):

    @unittest.expectedFailure
    def test_20_deux_artistes(self):
        """Correction « plusieurs artistes ».
        HYPOTHÈSE : artiste de l'album = « Alain Souchon & Laurent Voulzy »
        (noms reliés par le mot de liaison Discogs). Aujourd'hui : « Alain Souchon » seul."""
        res = run_main(RELEASES["deux_artistes"])
        self.assertEqual(res.frame("01.mp3", "TPE2"), "Alain Souchon & Laurent Voulzy")
        self.assertIn("Alain Souchon & Laurent Voulzy -- Album Test", res.dossiers)

    @unittest.expectedFailure
    def test_21_compilation_artiste_de_l_album(self):
        """Correction « compilations ».
        HYPOTHÈSE : artiste de l'album = « Various Artists » (et non « Various »)."""
        res = run_main(RELEASES["compilation"])
        self.assertEqual(res.frame("01.mp3", "TPE2"), "Various Artists")

    @unittest.expectedFailure
    def test_22_compilation_artiste_par_piste(self):
        """Correction « compilations » : chaque piste garde SON artiste (TPE1).
        Aujourd'hui toutes les pistes reçoivent « Various »."""
        res = run_main(RELEASES["compilation"])
        self.assertEqual(res.frame("01.mp3", "TPE1"), "Artiste Un")
        self.assertEqual(res.frame("02.mp3", "TPE1"), "Artiste Deux")

    @unittest.expectedFailure
    def test_23_compilation_marque_compilation(self):
        """Correction « compilations » : marque « compilation » (TCMP = 1), pour que
        Plex, Jellyfin, Clementine... ne découpent pas l'album."""
        res = run_main(RELEASES["compilation"])
        self.assertEqual(res.frame("01.mp3", "TCMP"), "1")

    @unittest.expectedFailure
    def test_24_suffixe_discogs_retire(self):
        """Correction « suffixe (2) ». Aujourd'hui : « Sublime (2) » dans le tag ET le dossier."""
        res = run_main(RELEASES["suffixe_2"])
        self.assertEqual(res.frame("01.mp3", "TPE1"), "Sublime")
        self.assertEqual(res.frame("01.mp3", "TPE2"), "Sublime")
        self.assertIn("Sublime -- Album Test", res.dossiers)

    @unittest.expectedFailure
    def test_25_oe_conserve_dans_les_tags(self):
        """Correction « caractères spéciaux » : « Cœur de Pirate » identique dans le tag
        et dans le dossier. Aujourd'hui le tag devient « Coeur de Pirate »."""
        res = run_main(RELEASES["oe"])
        self.assertEqual(res.frame("01.mp3", "TPE2"), "Cœur de Pirate")
        self.assertIn("Cœur de Pirate -- Album Test", res.dossiers)

    @unittest.expectedFailure
    def test_26_apostrophe_typographique_conservee(self):
        """Correction « caractères spéciaux » : « Guns N’ Roses » inchangé dans le tag
        (aujourd'hui l'apostrophe ’ devient ' et ne correspond plus au dossier)."""
        res = run_main(RELEASES["apostrophe"])
        self.assertEqual(res.frame("01.mp3", "TPE2"), "Guns N’ Roses")
        self.assertIn("Guns N’ Roses -- Album Test", res.dossiers)

    @unittest.expectedFailure
    def test_27_autres_tags_conserves(self):
        """Correction « ne plus tout effacer » : un commentaire et un champ perso déjà
        présents dans le fichier doivent survivre. Aujourd'hui tout est effacé."""

        def ajouter(paths):
            for path in paths:
                tags = ID3(path)
                tags.add(COMM(encoding=3, lang="fra", desc="", text="Ma note perso"))
                tags.add(TXXX(encoding=3, desc="MA_NOTE", text="à garder"))
                tags.save(path)

        res = run_main(RELEASES["simple"], prepare=ajouter)
        tags = res.tags["01.mp3"]
        self.assertTrue(any(k.startswith("COMM") for k in tags.keys()), list(tags.keys()))
        self.assertIn("TXXX:MA_NOTE", tags)

    @unittest.expectedFailure
    def test_28_echec_d_ecriture_visible(self):
        """Correction « erreurs visibles » : si l'écriture des tags échoue, le programme
        doit se terminer avec un code ≠ 0 (aujourd'hui : code 0, « succès » affiché)."""

        class EasyID3QuiEchoue(tg.EasyID3):
            def save(self, *args, **kwargs):
                raise OSError("disque plein (simulé)")

        with mock.patch.object(tg, "EasyID3", EasyID3QuiEchoue):
            res = run_main(RELEASES["simple"])
        self.assertNotEqual(res.exit_code, 0)

    @unittest.skip(
        "Règle à décider : option « conserver l'artiste de l'album existant » "
        "(nom de l'option non défini). À écrire avec la correction « ne plus tout effacer »."
    )
    def test_29_tpe2_existant_conserve_avec_option(self):
        """Fichier ayant déjà un TPE2 + option « conserver » : le TPE2 existant est gardé."""


# ===========================================================================
# GROUPE 3 : interface graphique (ignoré si PyQt6 n'est pas installé)
# ===========================================================================
try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # pas besoin d'écran
    from PyQt6.QtWidgets import QApplication

    _QT_OK = True
except Exception:  # PyQt6 absent
    _QT_OK = False


@unittest.skipUnless(_QT_OK, "PyQt6 non installé")
class TestInterfaceGraphique(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.gui = _load_module("tagger_gui_under_test", _find_script("TAGGER_GUI_PATH", "tagger_gui.py"))
        cls.win = cls.gui.MainWindow()

    def _remplir_dossier(self, tmp, valeurs):
        for n, valeur in valeurs.items():
            frames = [TPE2(encoding=3, text=valeur)] if valeur is not None else []
            make_mp3(os.path.join(tmp, f"{n:02d}.mp3"), track=n, frames=frames)
        self.win.inp_folder.setText(tmp)
        self.win._refresh_table()

    def test_40_champ_et_option_A(self):
        """Le champ « Artiste de l'album » transmet -A à tagger.py (et seulement s'il est rempli)."""
        self.win.inp_barcode.setText("123")
        self.win.inp_folder.setText("/tmp/x")
        self.win.inp_interprete.setText("")
        self.win.inp_albumartist.setText("")
        self.assertNotIn("-A", self.win._build_args())
        self.win.inp_albumartist.setText("Orchestre X")
        args = self.win._build_args()
        self.assertEqual(args[args.index("-A") + 1], "Orchestre X")

    def test_41_colonne_et_alertes(self):
        """Colonne « Artiste album » : cellule rouge si vide, violette si différent ; message d'alerte."""
        with tempfile.TemporaryDirectory() as tmp:
            self._remplir_dossier(tmp, {1: "Artiste A", 2: "Artiste B", 3: ""})
            table = self.win.table
            entetes = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
            self.assertEqual(entetes[4], "Artiste album")
            self.assertEqual(entetes[-1], "Qualité")  # la colonne Qualité a bien été décalée
            self.assertEqual(table.item(0, 4).background().color().name(), "#7b1fa2")
            self.assertEqual(table.item(2, 4).text(), "(vide)")
            self.assertEqual(table.item(2, 4).background().color().name(), "#d32f2f")
            texte = self.win.lbl_albumartist_check.text()
            self.assertIn("vide ou absent", texte)
            self.assertIn("différent selon les pistes", texte)

    def test_42_coherent(self):
        """Artiste de l'album identique partout : message ✓ et aucune cellule colorée."""
        with tempfile.TemporaryDirectory() as tmp:
            self._remplir_dossier(tmp, {1: "Orchestre", 2: "Orchestre"})
            self.assertTrue(self.win.lbl_albumartist_check.text().startswith("✓"))
            self.assertNotIn(
                self.win.table.item(0, 4).background().color().name(), ("#7b1fa2", "#d32f2f")
            )

    def test_43_dossier_invalide(self):
        """Dossier inexistant : tableau vide et message effacé (pas de plantage)."""
        self.win.inp_folder.setText("/dossier/qui/n/existe/pas")
        self.win._refresh_table()
        self.assertEqual(self.win.table.rowCount(), 0)
        self.assertEqual(self.win.lbl_albumartist_check.text(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
