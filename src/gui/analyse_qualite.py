#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""analyse_qualite – Analyse de la qualité des fichiers MP3 d'un dossier.

Ce module reprend le code de 33-mp3_quality_analyzer.py, avec ces différences :
  - pas de rapport CSV ;
  - pas de spectrogramme sauf pour les pistes douteuses
    (dans le sous-dossier « spectrograms_suspects ») ;
  - tout ce qui doit être affiché passe par une fonction `log(texte)` :
    l'interface graphique (tagger_gui) l'utilise pour remplir sa fenêtre de Log.

Principe : un MP3 de mauvaise qualité (ou un « faux » haut débit) se reconnaît
à une chute brutale du son à une hauteur précise (comme un coup de ciseaux).
Le script cherche cette chute. S'il n'en trouve pas, il ne conclut PAS que le
fichier est excellent : il écrit « Pas de coupure franche détectée ».

Utilisation seule (test en ligne de commande) :
    python analyse_qualite.py "/home/jm/Audio/MP3/"

Dépendances :
    pip install mutagen librosa soundfile matplotlib numpy pandas tqdm
"""

import io
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

warnings.filterwarnings("ignore")

# ============================================================
# RÉGLAGES
# ============================================================

DROP_DB_DEFAULT = 15      # chute minimale (en dB) pour parler de "coupure franche"
SEARCH_MIN_HZ = 4000      # on cherche la coupure à partir de cette hauteur
SEARCH_MAX_HZ = 21500     # ... jusqu'à cette hauteur
LOW_BITRATE_KBPS = 128    # en dessous, on signale "débit faible"
SPECTRO_DIRNAME = "spectrograms_suspects"


# ============================================================
# FONCTIONS D'ANALYSE
# ============================================================

def estimate_quality(cutoff_hz: float | None) -> str:
    """Traduit la hauteur de coupure en une appréciation (indicative)."""
    if cutoff_hz is None:
        return "Pas de coupure franche détectée"
    if cutoff_hz >= 19800:
        return "Excellent (~320 kbps)"
    elif cutoff_hz >= 19500:
        return "Très bon (~256 kbps)"
    elif cutoff_hz >= 18500:
        return "Bon (~192 kbps)"
    elif cutoff_hz >= 17000:
        return "Moyen (~160 kbps)"
    elif cutoff_hz >= 15500:
        return "Faible (~128 kbps)"
    else:
        return "Très faible (<128 kbps)"


def get_basic_info(filepath: Path) -> dict:
    from mutagen.mp3 import MP3

    info = {
        "fichier": filepath.name,
        "chemin": str(filepath),
        "bitrate_kbps": None,
        "sample_rate": None,
        "channels": None,
        "duration_s": None,
        "mode": None,
        "bitrate_mode": None,
        "cutoff_hz": None,
        "estimated_quality": None,
        "alerte": "",
        "douteux": False,
        "spectrum_error": None,
        "error": None,
    }
    try:
        audio = MP3(filepath)
        info["bitrate_kbps"] = round(audio.info.bitrate / 1000)
        info["sample_rate"] = audio.info.sample_rate
        info["channels"] = audio.info.channels
        info["duration_s"] = round(audio.info.length, 1)

        mode_map = {0: "Stereo", 1: "Joint-Stereo", 2: "Dual", 3: "Mono"}
        info["mode"] = mode_map.get(int(getattr(audio.info, "mode", -1)), "?")

        bm = getattr(audio.info, "bitrate_mode", None)
        info["bitrate_mode"] = getattr(bm, "name", str(bm)) if bm is not None else "?"
    except Exception as e:
        info["error"] = str(e)
    return info


def analyze_cutoff(filepath: Path, drop_db: float = DROP_DB_DEFAULT) -> dict:
    """
    Cherche la plus forte chute de niveau sonore entre SEARCH_MIN_HZ et
    SEARCH_MAX_HZ. Si la chute dépasse `drop_db`, c'est une coupure franche.
    """
    import numpy as np
    import librosa

    result = {
        "cutoff_hz": None,
        "estimated_quality": None,
        "spectrum_error": None,
    }
    try:
        y, sr = librosa.load(str(filepath), sr=44100, mono=True, duration=60)

        n_fft = 4096
        if len(y) < n_fft:
            raise ValueError("Fichier trop court pour être analysé")

        S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=1024))
        freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)

        # Niveau moyen par hauteur de son, en valeur absolue
        level_db = librosa.amplitude_to_db(
            np.mean(S, axis=1), ref=1.0, amin=1e-10, top_db=None
        )

        # Lissage (~430 Hz) sans effet de bord
        k = 40
        padded = np.pad(level_db, (k // 2, k - 1 - k // 2), mode="edge")
        smooth = np.convolve(padded, np.ones(k) / k, mode="valid")

        # Comparaison du niveau avec celui ~500 Hz plus haut
        step = 47
        i_min = int(np.searchsorted(freqs, SEARCH_MIN_HZ))
        i_max = int(np.searchsorted(freqs, SEARCH_MAX_HZ))
        i_max = min(i_max, len(smooth) - step)
        if i_max <= i_min:
            raise ValueError("Plage de recherche invalide")

        drops = smooth[i_min:i_max] - smooth[i_min + step:i_max + step]
        best = int(np.argmax(drops))

        if drops[best] >= drop_db:
            cutoff = float(freqs[i_min + best + step // 2])
            result["cutoff_hz"] = round(cutoff)
            result["estimated_quality"] = estimate_quality(cutoff)
        else:
            result["cutoff_hz"] = None
            result["estimated_quality"] = estimate_quality(None)
    except Exception as e:
        result["spectrum_error"] = str(e)
    return result


def generate_spectrogram(filepath: Path, output_dir: Path, cutoff: float | None = None,
                         suffix: str = "_suspect") -> str:
    import numpy as np
    import pandas as pd
    import librosa
    import librosa.display
    import matplotlib.pyplot as plt

    try:
        y, sr = librosa.load(str(filepath), sr=None, mono=True, duration=45)

        plt.figure(figsize=(14, 5.5))
        D = librosa.amplitude_to_db(
            np.abs(librosa.stft(y, n_fft=2048, hop_length=512)), ref=np.max
        )
        librosa.display.specshow(D, sr=sr, x_axis="time", y_axis="hz", cmap="magma")
        plt.colorbar(format="%+2.0f dB")

        has_cutoff = cutoff is not None and not pd.isna(cutoff)
        plt.title(f"{filepath.name}  |  Cutoff ≈ {cutoff:.0f} Hz" if has_cutoff else filepath.name)
        if has_cutoff:
            plt.axhline(y=cutoff, color="cyan", linestyle="--", lw=1.5,
                        label=f"Cutoff {cutoff:.0f} Hz")
            plt.legend(loc="upper right")
        plt.ylim(0, min(22050, sr // 2))
        plt.tight_layout()

        out_path = output_dir / f"{filepath.stem}{suffix}.png"
        plt.savefig(out_path, dpi=130, bbox_inches="tight")
        plt.close()
        return str(out_path)
    except Exception as e:
        plt.close("all")
        return f"Erreur: {e}"


def analyze_one(filepath: Path, drop_db: float = DROP_DB_DEFAULT) -> dict:
    info = get_basic_info(filepath)
    if info["error"]:
        info["alerte"] = "❌ Fichier illisible"
        return info

    info.update(analyze_cutoff(filepath, drop_db))

    bitrate = info.get("bitrate_kbps") or 0
    cutoff = info.get("cutoff_hz")
    # Pas de coupure détectée -> on ne soupçonne rien (valeur très haute)
    cutoff_cmp = cutoff if cutoff is not None else 99999

    if bitrate >= 320 and cutoff_cmp < 19500:
        info["alerte"] = "⚠️ FORT SUSPECT (320 kbps avec cutoff bas)"
        info["douteux"] = True
    elif bitrate >= 256 and cutoff_cmp < 18500:
        info["alerte"] = "⚠️ Suspect (haut bitrate + cutoff trop bas)"
        info["douteux"] = True
    elif bitrate >= 192 and cutoff_cmp < 17000:
        info["alerte"] = "⚠️ Qualité inférieure au bitrate annoncé"
        info["douteux"] = True
    elif 0 < bitrate < LOW_BITRATE_KBPS:
        info["alerte"] = f"ℹ️ Débit faible (< {LOW_BITRATE_KBPS} kbps)"
        info["douteux"] = False
    else:
        info["alerte"] = ""
        info["douteux"] = False

    return info


# ============================================================
# POINT D'ENTRÉE POUR L'INTERFACE
# ============================================================

def analyser_dossier(
    dossier: str,
    log: Callable[[str], None] = print,
    seuil_chute: float = DROP_DB_DEFAULT,
    jobs: int = 4,
) -> int:
    """Analyse les MP3 de `dossier` (sans les sous-dossiers) et écrit les
    résultats ligne par ligne via `log`.

    Les lignes d'erreur commencent par « ❌ ».
    Retourne 0 si l'analyse s'est bien passée, 1 sinon.
    """
    # --- Vérifications du dossier ---------------------------------
    dossier = (dossier or "").strip()
    if not dossier:
        log("❌ Aucun dossier audio renseigné.")
        return 1

    try:
        path = Path(dossier).expanduser().resolve()
    except Exception as e:
        log(f"❌ Chemin invalide : {dossier} ({e})")
        return 1

    if not path.exists():
        log(f"❌ Dossier introuvable : {path}")
        return 1
    if not path.is_dir():
        log(f"❌ Ce chemin n'est pas un dossier : {path}")
        return 1

    try:
        files = sorted(p for p in path.iterdir()
                       if p.is_file() and p.suffix.lower() == ".mp3")
    except PermissionError:
        log(f"❌ Accès refusé au dossier : {path}")
        return 1
    except OSError as e:
        log(f"❌ Impossible de lire le dossier {path} : {e}")
        return 1

    if not files:
        log(f"❌ Aucun fichier MP3 trouvé dans : {path}")
        return 1

    # --- Bibliothèques nécessaires --------------------------------
    try:
        import matplotlib
        matplotlib.use("Agg")  # pas de fenêtre, indispensable hors thread principal
        import pandas as pd
        from tqdm import tqdm
        import librosa  # noqa: F401
        import mutagen  # noqa: F401
    except ImportError as e:
        log(f"❌ Bibliothèque manquante : {e}. "
            "Installez-la avec : pip install mutagen librosa soundfile "
            "matplotlib numpy pandas tqdm")
        return 1

    # --- En-tête ---------------------------------------------------
    log(f"🔍 Analyse de {len(files)} fichier(s) MP3...")
    log(f"📁 Dossier de l'album : {path}")
    log(f"🎚️  Seuil de chute     : {seuil_chute} dB")
    log("")

    # --- Analyse en parallèle -------------------------------------
    results = []
    barre = io.StringIO()
    try:
        with ThreadPoolExecutor(max_workers=jobs) as executor:
            futures = {executor.submit(analyze_one, f, seuil_chute): f for f in files}
            for future in tqdm(as_completed(futures), total=len(files),
                               desc="Analyse", unit="fichier", file=barre, ncols=100, ascii=False):
                results.append(future.result())
    except Exception as e:
        log(f"❌ Erreur pendant l'analyse : {e}")
        return 1

    # tqdm écrit avec des retours chariot : on garde la dernière ligne (100 %)
    derniere = barre.getvalue().split("\r")[-1].strip()
    if derniere:
        log(derniere)
    log("")

    df = pd.DataFrame(results).sort_values("fichier").reset_index(drop=True)

    # --- Spectrogrammes : uniquement pour les pistes douteuses -----
    suspects = df[df["douteux"] == True]  # noqa: E712

    if len(suspects) > 0:
        spec_dir = path / SPECTRO_DIRNAME
        try:
            spec_dir.mkdir(exist_ok=True)
        except OSError as e:
            log(f"❌ Impossible de créer {spec_dir} : {e}")
        else:
            log(f"📊 Génération de {len(suspects)} spectrogramme(s)...")
            for _, row in suspects.iterrows():
                res = generate_spectrogram(Path(row["chemin"]), spec_dir,
                                           row.get("cutoff_hz"), "_suspect")
                if res.startswith("Erreur"):
                    log(f"❌ Spectrogramme impossible pour {row['fichier']} : {res}")
            log(f"✅ Spectrogrammes sauvegardés dans : {spec_dir}")
    else:
        log("✅ Aucune piste douteuse détectée → pas de spectrogramme généré.")

    # --- Tableau des résultats -------------------------------------
    colonnes = ["fichier", "bitrate_kbps", "bitrate_mode", "cutoff_hz",
                "estimated_quality", "alerte"]
    colonnes = [c for c in colonnes if c in df.columns]

    log("")
    log("=" * 110)
    log("RÉSULTATS DE L'ANALYSE")
    log("=" * 110)
    with pd.option_context("display.max_columns", None, "display.width", 220,
                           "display.max_colwidth", 55):
        for ligne in df[colonnes].to_string(index=False).split("\n"):
            log(ligne)

    # --- Statistiques ------------------------------------------------
    log("")
    log("-" * 60)
    log("STATISTIQUES")
    log("-" * 60)
    br = df["bitrate_kbps"].dropna()
    if len(br):
        log(f"Bitrate moyen déclaré        : {br.mean():.0f} kbps")
    co = df["cutoff_hz"].dropna()
    if len(co):
        log(f"Cutoff moyen (si détecté)    : {co.mean():.0f} Hz")
    log(f"Sans coupure franche         : {int(df['cutoff_hz'].isna().sum())}")
    log(f"Pistes douteuses             : {len(suspects)}")
    n_err = int(df["error"].notna().sum() + df["spectrum_error"].notna().sum())
    if n_err:
        log(f"❌ Erreurs de lecture/analyse : {n_err} fichier(s) concerné(s)")
        for _, row in df.iterrows():
            for champ in ("error", "spectrum_error"):
                if isinstance(row.get(champ), str) and row[champ]:
                    log(f"   - {row['fichier']} : {row[champ]}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage : python analyse_qualite.py <dossier>")
        sys.exit(2)
    sys.exit(analyser_dossier(sys.argv[1]))
