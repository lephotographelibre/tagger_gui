#!/usr/bin/python3
# -*- coding: iso-8859-1 -*-
"""
   tagger
    How to use discogs REST API - Explore Search using barcode
    Programme pour tagger un repertoire

    Authorization   --> https://www.discogs.com/fr/settings/developers
                        get the user's token (saisi a l'execution, jamais stocke dans le code)

    Docs           --> https://www.discogs.com/developers/#page:database,header:database-search

    - API Search Parameters barcode et API Release ID
    - Pas de gestion de la pagination cr le nombre de release retournee doit etre faible

positional arguments:
  BARCODE               Le code-barre de l"album CD (obligatoire)

options:
  -h, --help            show this help message and exit
  -f, --audio_folder AUDIO_FOLDER
                        Le chemin du dossier contenant les fichiers audio par defaut /home/jm/Audio/MP3/.
  --loglevel LOGLEVEL   Niveau de log (DEBUG, INFO, WARNING, ERROR) par defaut INFO
  -c, --compositeur     Compositeur Pour ajouter le nom du compositeur au nom sur morceau si il est present, sa valeur est True.
  -g, --genre GENRE     Genre de Musique pour force une valeur au niveau de l'album si il est present
  -r, --release RELEASE_ID
                        Discogs Release ID pour forcer une valeur si il est present
  -i, --interprete INTERPRETE
                        Interprete de l'album pour forcer une valeur si il est present

    Exemples:

    args: 081227819781 -f "/home/jm/Audio/MP3" --loglevel=DEBUG  (Madonna -- Veronica Electronica)
    args: "3 149020 949252" -f "/home/jm/Audio/MP3" --loglevel=DEBUG --compositeur
    args: "3 760014 192227" -f "/home/jm/Audio/MP3" --loglevel=DEBUG --compositeur  (pour les  args: "3 149020 949252" -f "/home/jm/Audio/MP3" --loglevel=DEBUG --compositeur -genre "Chanson Française" -release "30305858" -interprete "Michel Jonaz"


    V1.1 -  def tri_list_fichiers(chemin_dossier) - Optimisation Gemini tri fichiers suivant  le tracknumber et pas
            suivant les nom de fichiers
    V1.2 -  add compositeur et subtracks dans le titre du morceau
    V1.2.1 - add  -c, --compositeur     Compositeur Pour ajouter le nom du compositeur au nom sur morceaus'il est present par defaut si manquant False
    V1.2.2  add tag compositeur dans les tags ID3
    V1.2.3  bug fixing subtrack code add heading code to complement subtrack code
    V1.3    Generates ID3 title and missing tracknumber tags for audio files in a directory.
    V1.3.1  Bug fix recherche_subtracks() - Case sans substrack et headings
    V1.3.2  Bug fix #19 compositeurs with subtracks
    V1.3.3  Improve multiple calls to rechercher_compositeurs()
    V1.3.5  Apply Claude optims to funct rechercher_compositeurs() + type checking
    V1.3.6  args --genre -g on prend priotairement celui-ci
    V1.3.7  Set file permissions - Mettre les fichiers en Lesture/Ecriture pour tout le monde
    V1.3.8  Fix Issue #16 - barcode return multiple releases
    V1.3.9  Fix Issue #20 - when subtracks --> lTrack number is not correct
    V1.4.0  Gemini CLI - Optimisation: comptage en une seule passe count_tracks_from_discogs()
    V1.4.1  Fix issue #21 - Forcer l'utilisation d'une release (exceptionnelement)
    V1.4.2  Fix issue #22 - Forcer l'utilisation d'un interprete
    V2.0.0  Code Issue #23  - Analyse de la qualité audio
    V2.0.1  Fix bug heading found with release id 3157223 Agnes Obel
    V2.0.2  Fix bug heading found with release id  "8 86976 38542 2" Casablanca
    V2.1.0  Code Issue #25 Multi-CD Support use case "5051083152747" Ophélie Gaillard
    V2.1.1  Fix issue #26 Bug rechercher_subtracks() heading Key error
    V2.2    Fix issue #26 Bug rechercher_morceaux() heading Key error
    V2.2.1  Code support paramètre -r sous la forme [r14414132]
    V2.3    Fix bug #24 pb de caractères non latin1 dans une string mutagen
    V2.3.1  Fix _extract_composers() -  Add Author Use Case [r9598057]
    V2.3.2  Fix bug #24 pb de caractères non latin1 dans une string mutagen back to V2.2.1 remove unidecode EasyMP3 --> EasyID3
    V2.3.4  Fix #27 Alert if substracks AND Headings found
    V2.4  Fix Bug #27 - Using both headings and subtracks
    V2.4.1  Fix latin-1 encoding error: force ID3v2.4 (UTF-8) in apply_tags()
    V2.4.2  Fix latin-1 for URL frames (website/WOAR always latin-1) + sanitize Œ/œ

"""

import shutil
import sys
import os
import argparse
import logging
from pathlib import Path
from pprint import pprint

import socket
import requests
# Forcer IPv4 (evite les lenteurs dues aux tentatives IPv6 qui echouent)
_orig_getaddrinfo = socket.getaddrinfo
def _getaddrinfo_ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = _getaddrinfo_ipv4_only
import mutagen
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3
from mutagen.id3._frames import APIC
from mutagen.mp3 import EasyMP3, MP3
from mutagen import MutagenError  # type: ignore
from tabulate import tabulate

# V1.3.5 for Claude checks
from typing import Dict, List, Union, Optional, Any

# V1.3.7 set file permissions
import stat

# V2.3    Fix bug #24 pb de caractères non latin1 dans une string mutagen
# V2.3.2  Fix bug #24 pb de caractères non latin1 dans une string mutagen back to V2.2.1 remove unidecode EasyMP3 --> EasyID3
# from unidecode import unidecode

# --- Variable Globales -----------------------------------------------------------------------
VERSION = "V2.4.2"
DISCOGS_API_URL = "https://api.discogs.com"
# Le token Discogs n'est plus code en dur : il est fourni par la variable d'environnement
# DISCOGS_TOKEN (cas du lancement depuis tagger_gui.py) ou TOKEN_DISCOGS (optionnelle) ou saisi via une boite de dialogue
# au demarrage (voir ask_discogs_token()).
DISCOGS_TOKEN = (
    os.environ.get("DISCOGS_TOKEN", "") or os.environ.get("TOKEN_DISCOGS", "")
).strip()
HTTP_HEADERS = {
    "User-Agent": "JMClientRESTCli/1.0",
    "Authorization": f"Discogs token={DISCOGS_TOKEN}",
}
BARCODE = ""
AUDIO_FOLDER = ""
AUDIO_FOLDER_SAVE = ""
AUDIO_EXTENSIONS = (".mp3", ".flac", ".m4a")
ARTIST = ""
ALBUM_TITLE = ""
GENRE = ""
# COMPOSITEUR = False
RELEASE_ID = ""
INTERPRETE = ""


def ask_discogs_token() -> str:
    """
    Demande a l'utilisateur de saisir son token Discogs.
    - Boite de dialogue graphique (tkinter) si disponible, champ masque.
    - Sinon, saisie masquee dans le terminal (getpass).
    Returns: le token saisi (chaine vide si annulation)
    """
    try:
        import tkinter as tk
        from tkinter import simpledialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        token = simpledialog.askstring(
            "Token Discogs",
            "Saisissez votre token Discogs\n"
            "(https://www.discogs.com/settings/developers) :",
            show="*",
            parent=root,
        )
        root.destroy()
        return (token or "").strip()
    except Exception:
        # tkinter indisponible ou pas d'affichage --> saisie dans le terminal
        import getpass

        try:
            return getpass.getpass("Token Discogs : ").strip()
        except (EOFError, KeyboardInterrupt):
            return ""


def init_discogs_token() -> None:
    """
    Initialise le token Discogs : variable d'environnement DISCOGS_TOKEN si presente,
    sinon boite de dialogue de saisie. Met a jour DISCOGS_TOKEN et HTTP_HEADERS.
    Quitte le programme si aucun token n'est fourni.
    """
    global DISCOGS_TOKEN
    if not DISCOGS_TOKEN:
        DISCOGS_TOKEN = ask_discogs_token()
    if not DISCOGS_TOKEN:
        logging.error("Aucun token Discogs fourni - arret du programme.")
        sys.exit(1)
    # HTTP_HEADERS est modifie en place : toutes les fonctions qui l'utilisent voient le token
    HTTP_HEADERS["Authorization"] = f"Discogs token={DISCOGS_TOKEN}"


# Parser les arguments de la ligne de commande
def cmdline_args():
    """
    Parser les arguments de la ligne de commande
    Args:
    Returns: args a Parser object

    """
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        dest="BARCODE", type=str, help='Le code-barre de l"album CD (obligatoire)'
    )
    parser.add_argument(
        "-f",
        "--audio_folder",
        dest="AUDIO_FOLDER",
        type=str,
        help="Le chemin du dossier contenant les fichiers audio par defaut /home/jm/Audio/MP3/.",
        default="/home/jm/Audio/MP3/",
    )
    parser.add_argument(
        "--loglevel",
        type=str,
        help="Niveau de log (DEBUG, INFO, WARNING, ERROR) par defaut INFO",
        default="INFO",
    )
    # V1.2.1 - add  -c, --compositeur     Compositeur Pour ajouter le nom du compositeur
    parser.add_argument(
        "-c",
        "--compositeur",
        action="store_true",
        help="Compositeur Pour ajouter le nom du compositeur au nom sur morceau si il est present, "
        "sa valeur est True.",
    )
    # V1.3.6  args --genre -g on prend priotairement celui-ci
    parser.add_argument(
        "-g",
        "--genre",
        dest="GENRE",
        type=str,
        help="Genre de Musique pour force une valeur au niveau de l'album si il est present",
        default="default",
    )
    # V1.4.1  Fix issue #21 - Forcer l'utilisation d'une release
    parser.add_argument(
        "-r",
        "--release",
        dest="RELEASE_ID",
        type=str,
        help="Discogs Release ID pour forcer une valeur si il est present",
        default="default",
    )
    # V1.4.2  Fix issue #22 - Forcer l'utilisation d'un interprete
    parser.add_argument(
        "-i",
        "--interprete",
        dest="INTERPRETE",
        type=str,
        help="Interprete de l'album pour forcer une valeur si il est present",
        default="default",
    )

    return parser.parse_args()


# Check audiofile in folder
def get_audio_files(directory):
    """
    Retourne une liste triee de fichiers audio dans un dossier.
    Args:
        directory: Repertoire oe se trouvent les fichiers audio e tagger
    Returns:
        audio_files: Liste des fichiers audio dans un dossier
    """
    # cette version est en commentaire car renvoie une liste de fichiers tries d'apres le nom du fichier
    # audio_files_list = []
    # for filename in sorted(os.listdir(directory)):
    #     if filename.lower().endswith(AUDIO_EXTENSIONS):
    #         audio_files_list.append(os.path.join(directory, filename))

    # liste de fichiers audio tries by subtract
    audio_files_list = tri_list_fichiers(directory)
    return audio_files_list


# Funct get release using url
def get_release_data(url_release_id):
    """
    Recupere les donnees d'une publication depuis l'API Discogs.
    Args:
        release_id: url release ID

    Returns:
        JSON object response to API Discogs Release ID
    "
    """

    logging.debug(f"--- get_release_data() - Requesting data from {url_release_id}")
    try:
        response = requests.get(url_release_id, headers=HTTP_HEADERS, timeout=(10, 30))
        response.raise_for_status()  # Leve une exception pour les codes d'erreur HTTP
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Erreur lors de la requete e l'API Discogs : {e}")
        return None


# Funct.Telechargement image de pochette
def download_cover_art(image_url):
    """Telecharge une image de pochette."""
    if not image_url:
        return None
    try:
        response = requests.get(image_url, headers=HTTP_HEADERS, timeout=(10, 30))
        response.raise_for_status()
        logging.debug(
            f"---download_cover_art() Telechargement de la pochette : {image_url}"
        )
        return response.content
    except requests.exceptions.RequestException as e:
        logging.error(
            f"---download_cover_art() Erreur lors du telechargement de la pochette : {e}"
        )
        return None


# Funct. Copie de repertoire
def copier_repertoire(src, save):
    """
    Copie un repertoire source complet dans un repertoire de destination parent.
    Le repertoire source sera recree e l'interieur de la destination.

    Args:
        src (str): Chemin du dossier source e copier.
        dst_parent (str): Chemin du dossier parent de destination.

    """
    # etape 1 : Verifier si la source existe
    if not os.path.isdir(src):
        logging.error(
            f"--- copier_repertoire() - Le dossier source n'existe pas ou n'est pas un dossier : '{src}'"
        )
        return

    # etape 2 : Extraire le nom du dossier source

    # etape 3 : Construire le chemin de destination final
    chemin_destination_final = save

    logging.debug(f"--- copier_repertoire() - Source      : '{src}'")
    logging.debug(
        f"--- copier_repertoire() - Sauvergarde : '{chemin_destination_final}'"
    )

    try:
        # etape 4 : Copier l'arborescence
        # shutil.copytree copie le contenu de 'src' dans un NOUVEAU dossier
        # nomme 'chemin_destination_final'.
        # La destination ne doit pas deje exister.
        shutil.copytree(src, chemin_destination_final)
        logging.debug(f"- Succes ! La copie du repertoire est terminee.")

    except FileExistsError:
        logging.error(
            f"--- copier_repertoire() - Le dossier de sauvegarde existe deje : '{chemin_destination_final}'"
        )
        logging.error(
            f"--- copier_repertoire() - Veuillez le supprimer ou choisir une autre destination avant de reessayer."
        )
        sys.exit(1)
    except OSError as e:
        # Gerer d'autres erreurs possibles (permissions, etc.)
        logging.error(
            f"--- copier_repertoire() - Une erreur systeme est survenue : {e}"
        )
        sys.exit(1)
    except Exception as e:
        logging.error(
            f"--- copier_repertoire() - Une erreur inattendue est survenue : {e}"
        )
        sys.exit(1)


# merge tracklist and subtrack if needed
def get_subtrack(tracklist_list):
    """
    merge tracklist and subtrack if needed (classical mainly)

    Args:
        tracklist_list: List des tracks and subtracks

    Returns:
        merge_tracklist_list:   List des tracks and subtracks merged if needed
                                = Args tracklist_list if no subtrack
    """
    merge_tracklist_list = []
    tracklist = []
    # y a t il des subtracks -->       "type_": "index" instead of "type_": "track",
    IsThereSubtrack = False
    for tracklist in tracklist_list:
        if tracklist["type_"] == "index":
            IsThereSubtrack = True
            # logging.debug(f" il y a des subtracks {tracklist}")
            break

    if IsThereSubtrack:  # if substracks
        for tracklist in tracklist_list:
            titre_track = tracklist["title"]
            try:
                if len(tracklist["sub_tracks"]) > 0:  # il y des subtracks
                    # logging.debug(f"Il y a des subtracks")
                    for subtrack in tracklist["sub_tracks"]:
                        line_dict = dict(
                            {
                                "position": subtrack["position"],
                                "type_": subtrack["type_"],
                                "title": titre_track + "-" + subtrack["title"],
                                "duration": subtrack["duration"],
                            }
                        )
                        # logging.debug(f" subtrack {line_dict}")
                        merge_tracklist_list.append(line_dict)
            except KeyError as e:  # -- Key Error it's a track not a subtrack
                line_dict = dict(
                    {
                        "position": tracklist["position"],
                        "type_": tracklist["type_"],
                        "title": tracklist["title"],
                        "duration": tracklist["duration"],
                    }
                )
                # logging.debug(f"Erreur get_subtrack KeyError: {e} I's a track {line_dict}")
                merge_tracklist_list.append(line_dict)
        # return merge_tracklist_list
    else:  # if no subtrack  do nothing # return tracklist_list unmodified
        # logging.debug(f" il n'y a des subtracks {tracklist}")
        return tracklist_list

    return merge_tracklist_list


# Recupere les donnees de la release de discosg
def prepare_new_tags(
    release_data,
    track_number,
    total_tracks,
    ARTIST,
    ALBUM_TITLE,
    complete_trackname_dict,
    composer_dict,
):
    """Prepare un dictionnaire de nouveaux tags e partir des donnees Discogs."""
    if not release_data:
        return {}

    # Gestion des artistes multiples
    # artist_name = ', '.join([artist['name'] for artist in release_data.get('artists', [])])

    # Force l'utilisation de l'artiste passe en parametre
    artist_name = ARTIST

    # track_info = release_data.get('tracklist', [])[track_number - 1]

    tracklist_list = get_subtrack(release_data.get("tracklist", []))
    track_info = tracklist_list[track_number - 1]

    genres_list = release_data.get("genres", [])
    # par defaut genre = 1er element de la liste genre
    genre_album = genres_list[0]
    for genre in genres_list:
        if genre == "Classical":
            genre_album = "Classique"
    styles_list = release_data.get("styles", [])
    for style in styles_list:
        if style == "Baroque":
            genre_album = style

    # V1.3.6 if --genre
    if GENRE != "default" and len(GENRE) > 0:
        genre_album = GENRE

    # composer_dict = rechercher_compositeurs(release_data)

    # Liste des tags supporte par EsayMP3
    # Because of the simpler interface, only a few keys can be edited by EasyID3; to see them, use:
    # from mutagen.easyid3 import EasyID3
    # elogging.info(EasyID3.valid_keys.keys())
    # dict_keys(
    #         ['album', 'bpm', 'compilation', 'composer', 'copyright', 'encodedby', 'lyricist', 'length', 'media', 'mood',
    #          'grouping', 'title', 'version', 'artist', 'albumartist', 'conductor', 'arranger', 'discnumber', 'organization',
    #          'tracknumber', 'author', 'albumartistsort', 'albumsort', 'composersort', 'artistsort', 'titlesort', 'isrc',
    #          'discsubtitle', 'language', 'genre', 'date', 'originaldate', 'performer:*', 'musicbrainz_trackid', 'website',
    #          'replaygain_*_gain', 'replaygain_*_peak', 'musicbrainz_artistid', 'musicbrainz_albumid',
    #          'musicbrainz_albumartistid', 'musicbrainz_trmid', 'musicip_puid', 'musicip_fingerprint',
    #          'musicbrainz_albumstatus', 'musicbrainz_albumtype', 'releasecountry', 'musicbrainz_discid', 'asin',
    #          'performer', 'barcode', 'catalognumber', 'musicbrainz_releasetrackid', 'musicbrainz_releasegroupid',
    #          'musicbrainz_workid', 'acoustid_fingerprint', 'acoustid_id'])

    #     #'url' : release_data.get("uri")
    #     #'discogs_release_id': [str(release_data.get('id'))]
    # }

    new_tags = {
        "artist": ARTIST,
        "albumartist": ARTIST,
        "album": ALBUM_TITLE,
        "title": complete_trackname_dict[track_number],
        "genre": genre_album,
        "date": str(release_data.get("year", "")),
        "barcode": BARCODE,
        "composer": composer_dict[track_number],
        "website": release_data.get("uri"),
    }
    return new_tags


# ---------------------------------------------------------------------------
# V2.4.2  Fix latin-1 encoding error (robust)
# ---------------------------------------------------------------------------
# Les frames URL ID3 (WOAR / "website") sont TOUJOURS en latin-1 d'après la
# spécification ID3 — même en v2.4. L'URL Discogs contient souvent Œ, œ, etc.
# → on sanitise ces caractères avant d'écrire le tag.
# Les frames texte (title, album, artist…) passent en UTF-8 via ID3v2.4.
# ---------------------------------------------------------------------------

def _sanitize_id3_text(text: str, for_url: bool = False) -> str:
    """Remplace les caractères hors latin-1 (et quelques typographiques).

    Args:
        text: chaîne à nettoyer
        for_url: True pour les frames URL (WOAR) qui DOIVENT rester latin-1
    """
    if not isinstance(text, str):
        text = str(text) if text is not None else ""

    replacements = {
        "\u0152": "OE",   # Œ
        "\u0153": "oe",   # œ
        "\u2013": "-",    # –
        "\u2014": "-",    # —
        "\u2018": "'",    # ‘
        "\u2019": "'",    # ’
        "\u201c": '"',    # “
        "\u201d": '"',    # ”
        "\u00a0": " ",    # non-breaking space
        "\u2026": "...",  # …
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)

    if for_url:
        # Les frames URL ID3 n'acceptent que latin-1 : on force le remplacement
        return text.encode("latin-1", errors="replace").decode("latin-1")
    return text


# En utilsant mutagen appliquer les nouveaux tags aux fichiers audio
# V2.4.2  Fix latin-1 : sanitise + ID3v2.4 (UTF-8) pour les frames texte
def apply_tags(filepath, new_tags):
    """Applique les nouveaux tags à un fichier audio.

    - Frames texte  → ID3v2.4 (UTF-8)
    - Frames URL    → latin-1 (obligation de la norme ID3) après sanitisation
    """
    # Clés EasyID3 qui correspondent à des frames URL (toujours latin-1)
    URL_KEYS = {"website", "url"}

    try:
        # Supprimer les anciens tags pour repartir proprement en v2.4
        try:
            existing = ID3(filepath)
            existing.delete()
        except Exception:
            pass

        try:
            audio = EasyID3(filepath)
        except Exception:
            audio = EasyID3()

        for key, value in new_tags.items():
            if value is None:
                continue
            is_url = key in URL_KEYS
            clean = _sanitize_id3_text(str(value), for_url=is_url)
            logging.debug(f"- apply_tags) - key/Value = {key} / {clean} ")
            audio[key] = clean

        # ID3v2.4 → UTF-8 pour title, album, artist, etc.
        audio.save(filepath, v2_version=4)
        logging.info(
            f"- apply_tags) - Tags mis a jour pour : {os.path.basename(filepath)}"
        )
    except Exception as e:
        logging.error(
            f"- apply_tags) - Erreur lors de l'application des tags pour "
            f"{os.path.basename(filepath)}: {e}"
        )


# Funct. Insere un fichier image comme couverture de l'album dans chaque morceau audio
def apply_cover_art(filepath, cover_data):
    """Applique l'image de pochette e un fichier MP3."""
    try:
        audio = MP3(filepath, ID3=ID3)
        audio.tags.add(  # type: ignore
            APIC(
                encoding=3,  # 3 is for utf-8
                mime="image/jpeg",  # image/png or image/jpeg
                type=3,  # 3 is for the cover (front) image
                desc="Cover",
                data=cover_data,
            )
        )
        audio.save()
        logging.debug(
            f" - apply_cover_art() - Pochette ajoutee e : {os.path.basename(filepath)}"
        )
    except Exception as e:
        logging.error(
            f" - apply_cover_art() - Erreur lors de l'application de la pochette pour {os.path.basename(filepath)}: {e}"
        )


# eFunct. affiche tableau des tags UD3 des fichiers audio
def afficher_infos_album_tabulate(chemin_dossier):
    """
    Parcourt un dossier, extrait les metadonnees des fichiers audio et les
    affiche sous forme de tableau elegant en utilisant 'tabulate'.
    """
    donnees_tableau = []

    # Definition des en-tetes du tableau
    en_tetes = ["Chemin", "Position", "Titre", "Artiste", "Album", "Genre"]

    # # Parcourir les fichiers du dossier
    # fichiers_audio = [f for f in os.listdir(chemin_dossier) if f.endswith(('.mp3', '.flac', '.ogg'))]
    #
    # for fichier in fichiers_audio:
    #     chemin_fichier = os.path.join(chemin_dossier, fichier)
    #     try:
    #         audio = EasyID3(chemin_fichier)
    #         tracknumber = audio.get('tracknumber', ['Inconnu'])[0]
    #         titre = audio.get('title', ['Inconnu'])[0]
    #         artiste = audio.get('artist', ['Inconnu'])[0]
    #         album = audio.get('album', ['Inconnu'])[0]
    #         genre = audio.get('genre', ['Inconnu'])[0]
    #
    #         # Ajouter une ligne au tableau avec les informations
    #         donnees_tableau.append([tracknumber,titre, artiste, album, genre])

    # Parcourir les fichiers du dossier
    fichiers_audio = tri_list_fichiers(chemin_dossier)
    if len(fichiers_audio) == 0:
        logging.error(
            f" - afficher_infos_album_tabulate() - Erreur de lecture : {chemin_dossier}"
        )
    for chemin_fichier in fichiers_audio:
        try:
            audio = EasyID3(chemin_fichier)
            tracknumber = audio.get("tracknumber", ["Inconnu"])[0]  # type: ignore
            titre = audio.get("title", ["Inconnu"])[0]  # type: ignore
            artiste = audio.get("artist", ["Inconnu"])[0]  # type: ignore
            album = audio.get("album", ["Inconnu"])[0]  # type: ignore
            genre = audio.get("genre", ["Inconnu"])[  # type: ignore
                0
            ]  # pyright: ignore[reportOptionalSubscript]
            # year = audio.get('year', ['Inconnu'])[0]

            # Ajouter une ligne au tableau avec les informations
            donnees_tableau.append(
                [chemin_fichier, tracknumber, titre, artiste, album, genre]
            )
        except Exception:
            # Gerer les fichiers qui ne sont pas des fichiers audio valides
            logging.error(
                f" - afficher_infos_album_tabulate() - Erreur de lecture : {chemin_fichier}"
            )

    # Afficher le tableau. Le parametre 'headers' est utilise pour definir les titres de colonnes
    # et 'tablefmt' pour choisir le style du tableau (par exemple, "simple", "grid", "fancy_grid", "pipe", etc.)
    print(tabulate(donnees_tableau, headers=en_tetes, tablefmt="fancy_grid"))


# # Funct. Tri l'ordre des fichiers en fonction du tracknumber interne et pas suivant le nom des fichiers
def tri_list_fichiers(chemin_dossier):
    """
    Trie les fichiers audio d'un repertoire en fonction de leur numero de disque puis de piste (tracknumber).
    Generee par Gemini CLI

    Args:
        chemin_dossier: Le chemin complet du dossier e trier.

    Returns:
        Une liste des chemins de fichiers audio, triee par numero de disque puis de piste.

    """

    # V2.1.0  Code Issue #25 Multi-CD Support use case "5051083152747" Ophélie Gaillard
    def get_numeric_value(tag_value):

        # Extrait la première valeur numérique d'un tag.
        if not tag_value:
            return 0
        # La valeur du tag est une liste, on prend le premier élément.
        s_value = str(tag_value[0])
        # On ne garde que la partie avant un éventuel '/'
        numeric_part = s_value.split("/")[0]
        try:
            return int(numeric_part)
        except (ValueError, IndexError):
            return 0

    mp3_files_with_tags = []
    disc_numbers_found = set()

    # --- Étape 1: Collecter les informations de tous les fichiers ---
    for root, _, files in os.walk(chemin_dossier):
        for filename in files:
            if filename.lower().endswith(".mp3"):
                filepath = os.path.join(root, filename)
                try:
                    audio = ID3(filepath)
                    disc_number = get_numeric_value(audio.get("TPOS"))
                    track_number = get_numeric_value(audio.get("TRCK"))

                    mp3_files_with_tags.append(
                        {"path": filepath, "disc": disc_number, "track": track_number}
                    )
                    # Ajouter le numéro de disque au set pour analyse
                    if disc_number > 0:
                        disc_numbers_found.add(disc_number)

                except MutagenError as e:
                    logging.error(f"Erreur de lecture du fichier {filepath}: {e}")
                except Exception as e:
                    logging.error(f"Erreur inattendue avec le fichier {filepath}: {e}")

    # --- Étape 2: Déterminer la stratégie de tri ---
    # On considère un album comme multi-disques si on trouve plus d'un numéro de disque
    # ou si le plus grand numéro de disque est supérieur à 1.
    is_multi_disc = (
        len(disc_numbers_found) > 1
        or (max(disc_numbers_found) if disc_numbers_found else 1) > 1
    )

    # --- Étape 3: Trier en fonction de la stratégie ---
    if is_multi_disc:
        logging.debug(
            f"- tri_list_fichiers() - --> Album multi-disques detecte. Tri par disque, puis par piste."
        )
        # Clé de tri pour multi-disques
        sorting_key = lambda x: (x["disc"], x["track"])
    else:
        logging.debug(
            f"- tri_list_fichiers() - --> Album simple detecte. Tri par piste uniquement"
        )
        # Clé de tri pour un disque simple
        sorting_key = lambda x: x["track"]

    sorted_files = sorted(mp3_files_with_tags, key=sorting_key)

    # --- Étape 4: Fabrication de la liste des  fichiers triés par Disque puis Piste
    liste_des_fichiers_tries = []
    for item in sorted_files:
        liste_des_fichiers_tries.append(item["path"])

        if is_multi_disc:
            logging.debug(
                f"- tri_list_fichiers() - Disque: {item['disc']}, Piste: {item['track']} -> {item['path']}"
            )
        else:
            # Pour un album simple, inutile d'afficher le numéro de disque
            logging.debug(
                f"- tri_list_fichiers() - Piste: {item['track']} -> {item['path']}"
            )

    return liste_des_fichiers_tries


# Funct. Telecharge les images d'un album (meme fonction que precedemment) --- Discogs Releases API
def download_image(image_url, folder, filename):
    """
    Telecharge une image e partir d'une URL et l'enregistre dans un dossier specifie.

    - Construit l'URL de l'API pour recuperer les details de l'album (https://api.discogs.com/releases/{album_id}).
    - Definit un User-Agent dans les en-tetes de la requete. Discogs recommande (et parfois exige) un User-Agent descriptif.
    Changez-le pour correspondre e votre application.
    """
    os.makedirs(folder, exist_ok=True)
    params = {
        "token": DISCOGS_TOKEN,
    }
    # Manadatory --- Fix User-Agent ans pass it to the request
    # See also https://www.discogs.com/fr/forum/thread/863968?srsltid=AfmBOoqC7JannRKjsmuP5PsqO8Lrm4xvtrSunlof_ENFNblikVaAgL3T
    headers = {
        "User-Agent": "JMImageFetcher/1.0 +https://lephotographelibre.wordpress.com/"
    }
    try:
        # eresponse = requests.get(image_url, stream=True)
        response = requests.get(image_url, stream=True, params=params, headers=headers, timeout=(10, 30))
        response.raise_for_status()

        filepath = os.path.join(folder, filename)
        with open(filepath, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        logging.debug(f"Image telechargee: {filepath}")
    except requests.exceptions.RequestException as e:
        logging.debug(f"Erreur lors du telechargement de l'image {image_url}: {e}")


# Funct. de recherche de compositeurs
def rechercher_compositeurs(release_data, audio_files):
    """
    Recherche des compositeurs pour chaque morceau dans les données de release.

    Args:
        release_data: Dictionnaire contenant les informations de release avec tracklist
        audio_files: Liste des fichiers audio pour déterminer le nombre de tracks

    Returns:
        dict: Dictionnaire {index: compositeurs} où index commence à 1

    """

    def _extract_composers(extraartists: Optional[List[Dict[str, Any]]]) -> str:
        """
        Extrait les noms des compositeurs à partir de la liste extraartists.

        Args:
            extraartists: Liste des artistes/crédits ou None

        Returns:
            str: Noms des compositeurs séparés par des virgules, ou chaîne vide

        Raises:
            TypeError: Si extraartists n'est pas une liste ou None
        """
        if extraartists is None:
            return ""

        composers = []

        for credit in extraartists:

            role = credit.get("role")
            name = credit.get("name")
            # V2.3.1  Fix _extract_composers() -  Add Author
            if role in ["Composed By", "Written-By", "Author"] and isinstance(
                name, str
            ):
                composers.append(name if name.strip() else "Unknown")

        return ", ".join(composers) if composers else ""

    tracklist = release_data.get("tracklist", [])

    # Initialiser le dictionnaire avec le nombre de fichiers audio
    composer_dict = {i: "" for i in range(1, len(audio_files) + 1)}

    track_index = 0

    for item in tracklist:

        item_type = item.get("type_")

        if item_type == "track":
            track_index += 1
            if track_index in composer_dict:
                extraartists = item.get("extraartists")
                composer_dict[track_index] = _extract_composers(extraartists)

        elif item_type == "index":
            # Compositeur par défaut pour l'index
            extraartists = item.get("extraartists")
            index_composer = _extract_composers(extraartists)

            # Traiter les subtracks
            subtracks = item.get("sub_tracks", [])

            for subtrack in subtracks:
                track_index += 1
                if track_index in composer_dict:
                    # Pour l'instant, utilise le compositeur de l'index
                    # TODO: Implémenter la logique pour les compositeurs spécifiques aux subtracks
                    composer_dict[track_index] = index_composer

    return composer_dict


# V2.4  Fix Bug #27 - Using both headings and subtracks
def rechercher_morceaux(release_data):
    """
    Extrait les titres de chaque morceau à partir des données de la release.
    Gère correctement les structures avec 'headings', 'tracks' et 'index tracks' (subtracks).
    """
    morceaux_dict = {}
    tracklist_list = release_data.get("tracklist", [])

    # Initialisation
    for i in range(1, len(audio_files) + 1):
        morceaux_dict[i] = ""

    track_counter = 1

    for item in tracklist_list:
        item_type = item.get("type_")

        if item_type == "heading":
            # Les headings n'ont pas de titre de morceau, on les ignore ici.
            # La fonction recherche_subtracks s'en occupe pour les préfixes.
            continue

        elif item_type == "track":
            if track_counter <= len(audio_files):
                morceaux_dict[track_counter] = item.get("title", "")
            track_counter += 1

        elif item_type == "index":
            sub_tracks = item.get("sub_tracks", [])
            for subtrack in sub_tracks:
                if track_counter <= len(audio_files):
                    morceaux_dict[track_counter] = subtrack.get("title", "")
                track_counter += 1

    logging.debug(f" - recherche_morceaux morceaux_dict = {morceaux_dict}")

    return morceaux_dict


# V2.4  Fix Bug #27 - Using both headings and subtracks
def recherche_subtracks(release_data):
    """
    Construit un dictionnaire de préfixes de titre basé sur les 'headings' et 'index tracks'.
    Gère les cas où les 'headings' et les 'subtracks' (pistes d'index) coexistent.
    """
    subtrack_dict = {}
    tracklist_list = release_data.get("tracklist", [])

    # Initialisation
    for i in range(1, len(audio_files) + 1):
        subtrack_dict[i] = ""

    isThereSubtrack = False
    isThereHeading = False
    for tracklist in tracklist_list:
        if tracklist["type_"] == "index":
            isThereSubtrack = True
        if tracklist["type_"] == "heading":
            isThereHeading = True

    logging.debug(
        f" - recherche_subtracks() - Présence de subtracks: {isThereSubtrack}, Présence de headings: {isThereHeading}"
    )

    if not isThereSubtrack and not isThereHeading:
        logging.debug(
            " - recherche_subtracks() - Ni subtrack, ni heading. Rien à faire."
        )
        return subtrack_dict

    current_heading = ""
    track_counter = 1

    for item in tracklist_list:
        item_type = item.get("type_")

        if item_type == "heading":
            current_heading = item.get("title", "")
            logging.debug(
                f" - recherche_subtracks() - Nouveau heading: '{current_heading}'"
            )

        elif item_type == "track":
            if track_counter <= len(audio_files):
                if current_heading:
                    subtrack_dict[track_counter] = f"{current_heading} - "
                else:
                    subtrack_dict[track_counter] = ""
            track_counter += 1

        elif item_type == "index":
            index_title = item.get("title", "")
            sub_tracks = item.get("sub_tracks", [])
            for _ in sub_tracks:
                if track_counter <= len(audio_files):
                    prefix = f"{current_heading} - " if current_heading else ""
                    subtrack_dict[track_counter] = f"{prefix}{index_title}"
                track_counter += 1

    logging.debug(f" - recherche_subtracks() - subtrack_dict = {subtrack_dict}")

    return subtrack_dict


# Generates ID3 title and tracknumber tags for audio files in a directory.
def generate_tags_for_directory(directory_path):
    """
    Generates ID3 title and tracknumber tags for audio files in a directory.
    Title is filename without extension, tracknumber is alphabetical order.
    """
    logging.info(
        f" - generate_tags_for_directory () - Processing directory: {directory_path}"
    )

    audio_files = []
    # V2.0.1 Bug Fix Sort files before tagging
    # for entry in os.listdir(directory_path):
    for entry in sorted(os.listdir(directory_path)):

        full_path = os.path.join(directory_path, entry)
        if os.path.isfile(full_path):
            try:
                # Try to open with EasyID3 to check if it's a supported audio file
                # and if it has ID3 tags (or can have them).
                audio = EasyID3(full_path)
                audio_files.append(full_path)
            except mutagen.id3.ID3NoHeaderError:  # type: ignore
                # File is audio but has no ID3 header, still processable
                audio_files.append(full_path)
            except mutagen.MutagenError:  # pyright: ignore[reportPrivateImportUsage]
                # Not a supported audio file or corrupted
                pass
            except Exception as e:
                logging.debug(
                    f" - generate_tags_for_directory () - Could not process {full_path} - {e}"
                )

    # Sort files alphabetically for track numbering
    audio_files.sort()

    if not audio_files:
        logging.warning(
            f" - generate_tags_for_directory () -No supported audio files found in this directory."
        )
        return

    for i, file_path in enumerate(audio_files):
        track_number = i + 1
        file_name = os.path.basename(file_path)
        title = os.path.splitext(file_name)[0]

        try:
            # Use EasyID3 for simpler tag manipulation
            audio = EasyID3(file_path)

            if "tracknumber" in audio and audio["tracknumber"]:
                logging.debug(
                    f" - generate_tags_for_directory () - Skipping '{file_name}': Already has a tracknumber tag."
                )
                continue

            audio["title"] = title
            audio["tracknumber"] = str(track_number)

            audio.save()
            logging.info(
                f" - generate_tags_for_directory () - Tagged '{file_name}': Title='{title}', TrackNumber='{track_number}'"
            )
        except mutagen.MutagenError as e:  # pyright: ignore[reportPrivateImportUsage]
            logging.debug(
                f" - generate_tags_for_directory () - Error tagging {file_name}: {e}"
            )
        except Exception as e:
            logging.debug(
                f" - generate_tags_for_directory () - An unexpected error occurred with {file_name}: {e}"
            )


def set_read_write_permissions(directory_path):
    """
    Parcourt un répertoire et définit les permissions de lecture/écriture (666)
    pour tous les fichiers qu'il contient.
    """
    if not os.path.isdir(directory_path):
        logging.error(
            f"Erreur : Le chemin '{directory_path}' n'est pas un repertoire valide."
        )
        return

    # Permissions : lecture (r) et écriture (w) pour tout le monde.
    # Owner: rw-, Group: rw-, Others: rw-
    # En octal, cela correspond à 0o666.
    permissions = (
        stat.S_IRUSR
        | stat.S_IWUSR
        | stat.S_IRGRP
        | stat.S_IWGRP
        | stat.S_IROTH
        | stat.S_IWOTH
    )

    logging.info(
        f" - set_read_write_permissions() - Modification des permissions pour les fichiers dans le repertoire : {directory_path}\n"
    )

    try:
        # Liste tous les noms dans le répertoire
        for filename in os.listdir(directory_path):
            # Construit le chemin complet du fichier
            file_path = os.path.join(directory_path, filename)

            # Vérifie s'il s'agit bien d'un fichier (et non d'un sous-répertoire)
            if os.path.isfile(file_path):
                try:
                    # Change les permissions du fichier
                    os.chmod(file_path, permissions)
                    logging.debug(f"  [OK] Permissions mises à jour pour : {filename}")
                except OSError as e:
                    logging.error(
                        f"  [Erreur] Impossible de modifier '{filename}': {e}"
                    )
    except Exception as e:
        logging.error(f"Une erreur générale est survenue : {e}")

    logging.debug(f" - generate_tags_for_directory () - Opération terminée.")


# V1.3.8 Bug Issue #16 barcode retourne plusieurs releases
def select_release(release_url_list: list[str]) -> str | None:
    """
    Sélectionne la meilleure URL de release à partir d'une liste.
    code optimisé par Gemini

    La stratégie est la suivante :
    1. Chercher une release "master" et extraire sa "main_release_url".
    2. Si aucune "main_release_url" valide n'est trouvée, chercher la première
       release "standard" qui retourne des données valides.

    Args:
        release_url_list: Une liste de chaînes contenant les URL des releases.

    Returns:
        L'URL de la release sélectionnée, ou None si aucune n'est trouvée.
    """
    master_urls = [url for url in release_url_list if "masters" in url]
    other_release_urls = [
        url for url in release_url_list if "releases" in url and "masters" not in url
    ]

    # 1. On traite les masters en priorité
    logging.info(
        f" - select_release() - Recherche parmi {len(master_urls)} URL de master(s)..."
    )
    for url in master_urls:
        master_data = get_release_data(url)
        if not master_data:
            logging.warning(
                f" - select_release() - Aucune donnée retournée pour l'URL master : {url}"
            )
            continue  # On passe au master suivant

        main_release_url = master_data.get("main_release_url")
        if main_release_url:
            logging.info(
                f" - select_release() - URL principale trouvée via master : {main_release_url}"
            )
            return main_release_url
        else:
            logging.warning(
                f" - select_release() - Le master {url} ne contient pas de 'main_release_url'."
            )

    # 2. Si aucun master n'a fonctionné, on traite les autres releases
    logging.info(
        f" - select_release() - Recherche parmi {len(other_release_urls)} URL de release(s) standard..."
    )
    for url in other_release_urls:
        release_data = get_release_data(url)
        if release_data:
            logging.info(f" - select_release() - Release valide trouvée : {url}")
            return url
        else:
            logging.warning(
                f" - select_release() - Aucune donnée retournée pour la release : {url}"
            )

    logging.error(
        f" - select_release() - Aucune release valide n'a pu être trouvée dans la liste fournie."
    )
    return None


# V1.3.9 Issue #20 count real tracks and not subtracks
# V1.4.0 Optimisation: comptage en une seule passe
def count_tracks_from_discogs(release_data):
    """Compte le nombre de pistes réelles dans les données d'une release Discogs.

    Cette fonction parcourt la tracklist et compte les pistes individuelles.
    Elle gère correctement les "index tracks" qui contiennent des sous-pistes ("sub_tracks").

    Args:
        release_data (dict): Le dictionnaire contenant les données de la release,
                             généralement obtenu depuis l'API Discogs.

    Raises:
        TypeError: Si la "tracklist" n'est pas une liste.

    Returns:
        int: Le nombre total de pistes réelles.
    """
    tracklist = release_data.get("tracklist", [])

    if not isinstance(tracklist, list):
        raise TypeError(
            f"La tracklist doit être une liste, mais le type {type(tracklist).__name__} a été reçu."
        )

    total_tracks = 0
    for item in tracklist:
        # On s'assure que l'élément est un dictionnaire pour éviter les erreurs
        if not isinstance(item, dict):
            continue

        item_type = item.get("type_")

        if item_type == "track":
            total_tracks += 1
        elif item_type == "index":
            sub_tracks = item.get("sub_tracks", [])
            # On s'assure que sub_tracks est bien une liste avant de la compter
            if isinstance(sub_tracks, list):
                total_tracks += len(sub_tracks)

    return total_tracks


# V2.0.0  Code Issue #23  - Analyse de la qualité audio
def analyze_mp3_files(directory):
    """Analyse tous les fichiers MP3 dans le répertoire donné."""

    def _evaluate_audio_quality(bitrate_kbps):
        """Retourne une evaluation textuelle simple basee sur le bitrate."""
        if bitrate_kbps >= 300:
            return "Excellente (equivalent 320 kbps)"
        elif bitrate_kbps >= 240:
            return "Tres bonne (equivalent 256 kbps)"
        elif bitrate_kbps >= 180:
            return "Bonne (equivalent 192 kbps)"
        elif bitrate_kbps >= 120:
            return "Moyenne (equivalent 128 kbps)"
        else:
            return "Faible (< 128 kbps)"

    logging.info(
        f"- analyze_mp3_files() - Analyse des fichiers MP3 dans le dossier : {directory}\n"
    )
    found_files = False

    for root, _, files in os.walk(directory):
        for filename in sorted(files):
            if filename.lower().endswith(".mp3"):
                found_files = True
                file_path = os.path.join(root, filename)
                try:
                    audio = MP3(file_path)

                    # On vérifie que .info et ses attributs existent
                    #  PyrPylance dans VSCode n'est pas certain que l'objet audio.info contiendra toujours un attribut bitrate. Même si cela fonctionne dans la plupart des cas, il est plus sûr de vérifier la présence de l'attribut avant de l'utiliser.

                    if (
                        hasattr(audio, "info")
                        and hasattr(audio.info, "bitrate")
                        and hasattr(audio.info, "sample_rate")
                    ):
                        # Le bitrate est en bps, on le convertit en kbps pour la lisibilité
                        bitrate_kbps = (
                            audio.info.bitrate  # pyright: ignore[reportAttributeAccessIssue]
                            / 1000  # pyright: ignore[reportAttributeAccessIssue]
                        )  # pyright: ignore[reportAttributeAccessIssue]
                        sample_rate_hz = audio.info.sample_rate  # type: ignore

                        quality = _evaluate_audio_quality(bitrate_kbps)

                        logging.info(
                            f"- analyze_mp3_files() - Fichier : {filename} ---"
                        )
                        # print(f"  Chemin : {file_path}")
                        logging.info(
                            f"- analyze_mp3_files() - Debit: {bitrate_kbps:.0f} kbps - Frequence : {sample_rate_hz} Hz - Qualite : {quality}"
                        )
                        # logging.info("-" * (len(filename) + 12) + "\n")
                    else:
                        logging.error(
                            f"- analyze_mp3_files() - --- Fichier : {filename} ---"
                        )
                        logging.error(
                            f"- analyze_mp3_files() - --- Erreur: Impossible de lire les informations de bitrate ou de frequence du fichier."
                        )
                        # logging.error("-" * (len(filename) + 12) + "\n")

                except MutagenError as e:
                    logging.error(
                        f"- analyze_mp3_files() - --- Fichier : {filename} ---"
                    )
                    logging.error(
                        f"- analyze_mp3_files() - --- Erreur: Impossible de lire les informations du fichier. Ce n'est peut-être pas un MP3 valide."
                    )
                    logging.error(
                        f"- analyze_mp3_files() - --- Détail de l'erreur : {e}"
                    )
                    # logging.error("-" * (len(filename) + 12) + "\n")

    if not found_files:
        logging.error(
            f"- analyze_mp3_files() - --- Aucun fichier MP3 n'a été trouvé dans le dossier spécifié."
        )


# V2.2.1  Code support paramètre -r sous la forme [r14414132]
def clean_release_id(release_id):
    """
    Nettoie l'identifiant de la release en supprimant les caractères non numériques autour.
    Gère les formats comme "10515430", "[r10515430]" ou "[r10515430}".
    """
    # Supprime les caractères '[', 'r', ']' et '}' du début et de la fin de la chaîne.
    return release_id.strip("[]r}")


# main
def main():

    logging.debug(
        f"--- main() ---- Démarrage Mode Deboggage ON  -----------------------------------------"
    )

    # 1 - Recherche release avec barcode -----------------------------------------------------------------------------------
    search_url = "https://api.discogs.com/database/search"
    params = {
        "barcode": BARCODE,
        "token": DISCOGS_TOKEN,
        "page": 1,
    }

    page = 1
    release_url_list = []
    # eSearch using barcode as parameter
    response = requests.get(search_url, params=params, headers=HTTP_HEADERS, timeout=(10, 30))

    if response.status_code == 200:
        logging.debug(f"--- main() ---- Call URL Search Page({page})  : {response.url}")
        data = response.json()
        results = data.get("results", [])
    else:
        logging.error(f"{response.status_code}")
        sys.exit(0)

    # pprint(results)

    for result in results:
        logging.debug("Release URL --> " + result["resource_url"])
        release_url_list.append(result["resource_url"])

    release_url = ""
    if len(release_url_list) == 0:
        logging.error(
            f"--- main() ---- Pas de release trouve avec ce barcode {BARCODE}"
        )
    elif len(release_url_list) == 1:
        logging.info(f"--- main() - Release URL selectionnee : {release_url_list[0]}")
        release_url = release_url_list[0]
    elif len(release_url_list) > 1:
        logging.warning(
            f"--- main() - Il y a plusieurs releases associees avec ce code-barre"
        )
        logging.warning(
            f"--- main() - Il y a plusieurs releases associees avec ce code-barre {release_url_list}"
        )
        """ for release in release_url_list:
            if "releases" in release:  # contient la chaine "releases" et pas master
                release_url = release
                logging.info(f"--- main() - Release URL selectionnee : {release_url}")"""
        # V1.3.8 Bug Issue #16 barcode retourne plusieurs releases
        release_url = select_release(release_url_list)
        if release_url is None:
            logging.error(
                f"--- main() ---- Pas de release trouve avec ce barcode {BARCODE}"
            )

    # V1.4.1  Fix issue #21 - Forcer l'utilisatyion d'une release passée en paramètre
    # logging.warning( f"--- main() -  Release forcee = {RELEASE_ID} + args {args.RELEASE_ID}")
    if RELEASE_ID != "default":
        logging.warning(
            f"--- main() - On force l'utilisation de la Release {RELEASE_ID}"
        )
        release_url = f"https://api.discogs.com/releases/{RELEASE_ID}"

    # 2 - Recherche release avec Release ID URL
    # --------------------------------------------------------------------------------
    logging.info(
        f"--- main() - Recherche release de la Release {release_url} -----------------------------------------"
    )
    release_data = get_release_data(release_url)
    if not release_data:
        logging.error(
            f"--- main() ---- Pas de donnees trouvees avec cette release {release_url}"
        )
        sys.exit(1)

    # V1.3.9 Issue #20 Track number is not correct
    # if len(audio_files) != len(release_data.get("tracklist", [])):
    if len(audio_files) != count_tracks_from_discogs(release_data):
        logging.warning(
            f"--- main() - Le nombre de fichiers audio ({len(audio_files)}) ne correspond pas au nombre de pistes sur Discogs ({count_tracks_from_discogs(release_data)})."
        )
        # On continue quand meme, mais on le signale
    else:
        logging.info(
            f"--- main() - Le nombre de fichiers audio ({len(audio_files)})  correspond  au nombre de pistes sur Discogs ({count_tracks_from_discogs(release_data)})."
        )
    website_page = release_data.get("uri")
    logging.info(f"--- main() - Website URL {website_page}")

    # 2.1 - Constructiion tracklist e partir des donnees de la release (tracklist, sub-tracks, compositeurs)

    # test recherche compositeur
    morceaux_dict = rechercher_morceaux(release_data)
    logging.debug(f"--- main() - rechercher_Morceaux...{morceaux_dict}")

    # test recherche compositeur
    logging.debug(f"--- main() - Rechercher_compositeur...")
    composers_dicts = rechercher_compositeurs(release_data, audio_files)
    logging.debug(f"--- main() - rechercher_compositeur...{composers_dicts}.")

    # test recherche Subtracks
    logging.debug(f"--- main() - rechercher_subtracks...")
    subtrack_dict = recherche_subtracks(release_data)
    logging.debug(f"--- main() - recherche_subtracks...{subtrack_dict}")

    # efinal constituons la liste des noms de completsmorceaux
    complete_trackname_dict = {}
    i = 1
    a = len(audio_files)
    # for track in enumerate(audio_files):
    # if subtrack_dict[i] == "" and composers_dicts[i] == "":
    #     complete_trackname_dict[i] = morceaux_dict[i]
    # elif subtrack_dict[i] != "" and composers_dicts[i] == "":
    #     complete_trackname_dict[i] = f"{subtrack_dict[i]} {morceaux_dict[i]}"
    #
    # if composers_dicts[i] != "" and not args.compositeur:
    #     complete_trackname_dict[i] = f"{complete_trackname_dict[i]} ({composers_dicts[i]})"
    for track in enumerate(audio_files):
        if not args.compositeur:
            complete_trackname_dict[i] = f"{subtrack_dict[i]} {morceaux_dict[i]}"
        elif args.compositeur and composers_dicts[i] == "":
            complete_trackname_dict[i] = f"{subtrack_dict[i]} {morceaux_dict[i]}"
        elif args.compositeur and composers_dicts[i] != "":
            complete_trackname_dict[i] = (
                f"{subtrack_dict[i]} {morceaux_dict[i]} ({composers_dicts[i]})"
            )
        logging.debug(f"--- main()- complete trackname - {complete_trackname_dict[i]}")
        i = i + 1

    # 3. Application des tags ID3 -------------------------------------------------------------------------------------
    logging.info(f"--- main() - Mise en oeuvre des modifications tagID3...")
    # Telechargement de la pochette
    cover_url = release_data.get("images", [{}])[0].get("uri")
    cover_data = download_cover_art(cover_url)
    # Artiste et Titre de l'album
    ARTIST = release_data.get("artists", [{}])[0].get("name")
    ALBUM_TITLE = release_data.get("title")

    # V1.4.2  Fix issue #22 - Forcer l'utilisation d'un interprete
    if INTERPRETE != "default":
        ARTIST = INTERPRETE

    # V2.0.1  Fix bug heading found with release id 3157223 Agnes Obel
    audio_file_sort_by_trackname = tri_list_fichiers(AUDIO_FOLDER)
    # logging.debug(f"--- main() - Modification en cours .... {audio_file_sort_by_trackname}")

    total_tracks = len(audio_files)
    try:  # pour chaque morceau
        # V2.0.1  Fix bug heading found with release id 3157223 Agnes Obel
        for i, filepath in enumerate(audio_file_sort_by_trackname, 1):

            logging.debug(f"--- main() - Modification en cours .... " + filepath)
            new_tags = prepare_new_tags(
                release_data,
                i,
                total_tracks,
                ARTIST,
                ALBUM_TITLE,
                complete_trackname_dict,
                composers_dicts,
            )
            # pprint(new_tags)
            # logging.debug(f"--- main() - Modification en cours .... " + str(release_data))
            apply_tags(filepath, new_tags)
            if cover_data:
                logging.debug(f"--- main() - Mise e jour pochette : {i}/{total_tracks}")
                apply_cover_art(filepath, cover_data)
    except Exception as e:
        logging.error(f"--- main() - Mise e jour {e}")
        exit(1)
    logging.info(
        f"--- main() - Toutes les modifications ont ete appliquees avec succes."
    )

    # 4 - Telecharge toutes les images dans le folder
    images_list = release_data.get("images", [])

    if images_list:
        logging.info(
            f"--- main() - Telechargement de {len(images_list)} images pour l'album."
        )
        for i, img in enumerate(images_list):
            image_url = img.get("uri")
            if image_url:
                filename = f"album_image_{i + 1}.jpg"
                download_image(image_url, AUDIO_FOLDER, filename)
                logging.info("--- main() - .")
            else:
                logging.debug(
                    f"--- main() ---- Avertissement: URL d'image introuvable pour l'image {i + 1}."
                )
    else:
        logging.info(
            f"--- main() ---- Aucune image trouvee ou une erreur s'est produite lors de la recuperation des images de l'album."
        )

    # 5. Affiche tags  -------------------------------------------------------------------------------------
    chemin_dossier_album = AUDIO_FOLDER
    afficher_infos_album_tabulate(chemin_dossier_album)

    # 6. Mise aux normes nom de repertoire MP3 -> "ARTIST -- ALBUM_TITLE"

    # !! en supprimant les caracteres / dans le titre de l'album
    ARTIST = release_data.get("artists", [{}])[0].get("name").replace("/", "-")

    # V1.4.2  Fix issue #22 - Forcer l'utilisation d'un interprete
    if INTERPRETE != "default":
        ARTIST = INTERPRETE

    ALBUM_TITLE = release_data.get("title").replace("/", "-")

    AUDIO_FOLDER_SAVE = os.path.join(
        Path(AUDIO_FOLDER).parent, f"{ARTIST} -- {ALBUM_TITLE}"
    )
    copier_repertoire(AUDIO_FOLDER, AUDIO_FOLDER_SAVE)
    logging.info(f"--- main() ---- Sauvegarde finale dans  {AUDIO_FOLDER_SAVE}")

    #  7 Analyse de la qualité audio

    # V2.0.0  Code Issue #23  - Analyse de la qualité audio
    logging.info(f"--- main() ---- Analyse de la qualité audio dans  {AUDIO_FOLDER}")
    analyze_mp3_files(AUDIO_FOLDER_SAVE)

    # 100. Fin -------------------------------------------------------------------------------------

    logging.info(
        f"--- main() ---- Fin du programme -----------------------------------------"
    )
    sys.exit(0)  # 0 (the default) means success, non-zero means failure.


# --- Main ----------------------------------------------------------------------------------------------
if __name__ == "__main__":

    if sys.version_info < (3, 10, 0):
        sys.stderr.write(
            "Python 3.5 ou superieur est necessaire pour executer ce scriptt\n"
        )
        sys.exit(1)

    # - Mise en place du parser pour les parametres apsses sur la ligne de commande
    args = cmdline_args()

    # - Configuration du logging
    numeric_level = getattr(logging, args.loglevel.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Niveau de log invalide: {args.loglevel}")
    logging.basicConfig(
        level=numeric_level, format="%(asctime)s - %(levelname)s - %(message)s"
    )
    logging.debug(f"- Configuration du logging -  Done")
    logging.info(
        f"------ Demarrage barcode {VERSION} -----------------------------------------"
    )

    # - Sauvegrade comme variables globales
    BARCODE = args.BARCODE
    AUDIO_FOLDER = args.AUDIO_FOLDER
    GENRE = args.GENRE
    # V2.2.1  Code support paramètre -r sous la forme [r14414132]
    RELEASE_ID = clean_release_id(args.RELEASE_ID)
    INTERPRETE = args.INTERPRETE

    logging.info(
        f"------ Variables Globales : {BARCODE}  +  {AUDIO_FOLDER} + args.compositeur= {args.compositeur} + GENRE = {GENRE} + RELEASE_ID = {RELEASE_ID} + INTERPRETE = {INTERPRETE} ----------"
    )

    # - Token Discogs : variable d'environnement ou boite de dialogue de saisie
    init_discogs_token()

    # - Verifications initiales ---
    if not os.path.isdir(AUDIO_FOLDER):
        logging.error(f"Le dossier specifie n'existe pas : {AUDIO_FOLDER}")
        sys.exit()

    audio_files = get_audio_files(AUDIO_FOLDER)
    if not audio_files:
        logging.error(f"Aucun fichier audio trouve dans : {AUDIO_FOLDER}")
        sys.exit()

    #  V1.3.7 Set file permissions - Mettre les fichiers en Lesture/Ecriture pour tout le monde
    set_read_write_permissions(AUDIO_FOLDER)

    # - Sauvegarder folder avant modification --> dossier MP3_SAVE
    AUDIO_FOLDER_SAVE = os.path.join(Path(AUDIO_FOLDER).parent, "MP3_SAVE")
    copier_repertoire(AUDIO_FOLDER, AUDIO_FOLDER_SAVE)

    # Check si audio tags  missing ID3 tracknumber
    generate_tags_for_directory(AUDIO_FOLDER)
    logging.info(
        f" - Verifications initiales missing ID3 tracknumber - Tagging complete."
    )

    # - Execute Main
    main()
