#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""tagger_gui – Interface graphique Qt6 pour le script tagger.

Panneau gauche  : Paramètres correspondant aux arguments de la ligne de commande.
Panneau droit   : Tableau des pistes avec colonne « Qualité » codée en couleur
                  sur 5 niveaux (rouge → vert).
Section images  : Préaperçu des images d'album téléchargées par le tagger.

Exécution :
    pyenv activate venv_tagger
    python src/gui/tagger_gui.py
"""

import sys
import os
import re
import subprocess

from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QCheckBox,
    QTableWidget,
    QTableWidgetItem,
    QFileDialog,
    QTextEdit,
    QGroupBox,
    QFormLayout,
    QSplitter,
    QHeaderView,
    QGridLayout,
    QScrollArea,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QEvent
from PyQt6.QtGui import QColor, QIcon, QPixmap, QFont

from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3


# ---------------------------------------------------------------------------
# Qualité audio – 5 niveaux ordonnés du meilleur au pire.
#   (seuil_min kbps, label, couleur_fond, couleur_texte)
# ---------------------------------------------------------------------------
_QUALITY_LEVELS: list[tuple[int, str, str, str]] = [
    (300, "Excellente", "#2E7D32", "#ffffff"),
    (240, "Très bonne", "#66BB6A", "#000000"),
    (180, "Bonne", "#FDD835", "#000000"),
    (120, "Moyenne", "#FF9800", "#ffffff"),
    (0, "Faible", "#D32F2F", "#ffffff"),
]


def _evaluate_quality(bitrate_kbps: float) -> tuple[str, str, str]:
    """Retourne (label, bg_hex, fg_hex) pour un bitrate en kbps."""
    for threshold, label, bg, fg in _QUALITY_LEVELS:
        if bitrate_kbps >= threshold:
            return label, bg, fg
    return "Faible", "#D32F2F", "#ffffff"


# ---------------------------------------------------------------------------
# Worker – exécute tagger.py dans un thread séparé
# ---------------------------------------------------------------------------
class _TaggerWorker(QThread):
    log_line = pyqtSignal(str)  # une ligne émise en temps réel
    finished = pyqtSignal(int)  # code de retour du processus

    def __init__(self, args: list[str], script_path: str, env: dict | None = None):
        super().__init__()
        self._args = args
        self._script_path = script_path
        self._env = env  # environnement personnalisé transmis au subprocess

    def run(self):
        cmd = [sys.executable, self._script_path] + self._args
        self.log_line.emit(f"[CMD] {' '.join(cmd)}")
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # merge stderr → stdout
                text=True,
                bufsize=1,  # ligne par ligne
                env=self._env,
            )
            for line in iter(process.stdout.readline, ""):
                self.log_line.emit(line.rstrip("\n"))
            process.wait()
            self.finished.emit(process.returncode)
        except Exception as exc:
            self.log_line.emit(f"[ERREUR] {exc}")
            self.finished.emit(1)


# ---------------------------------------------------------------------------
# Label cliquable – utilisé pour les miniatures d'images album
# ---------------------------------------------------------------------------
class _ClickableLabel(QLabel):
    """QLabel qui émet clicked(str) avec le chemin du fichier source."""

    clicked = pyqtSignal(str)

    def __init__(self, image_path: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._image_path = image_path

    def event(self, ev: QEvent) -> bool:
        if ev.type() == QEvent.Type.MouseButtonRelease:
            self.clicked.emit(self._image_path)
            return True
        return super().event(ev)


# ---------------------------------------------------------------------------
# Fenêtre principale
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(1400, 820)
        self._worker: _TaggerWorker | None = None

        # tagger.py est dans src/ ; ce fichier est dans src/gui/
        self._script_path = os.path.normpath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tagger.py")
        )

        # Titre de la fenêtre avec le numéro de version lu dans tagger.py
        version = _read_tagger_version(self._script_path)
        title = "Tagger GUI – Discogs Audio Tagger"
        self.setWindowTitle(f"{title} – tagger {version}" if version else title)
        self._build_ui()

    # ------------------------------------------------------------------
    # Construction de l'interface
    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(6)

        # ── Splitter : panneau gauche | panneau droit ──────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStretchFactor(0, 1)  # gauche
        splitter.setStretchFactor(1, 3)  # droite
        root.addWidget(splitter, stretch=1)

        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())

        # ── Zone de log en bas ─────────────────────────────────────────
        log_group = QGroupBox("Log")
        log_vbox = QVBoxLayout(log_group)
        log_vbox.setContentsMargins(4, 4, 4, 4)
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumHeight(180)
        self.log_edit.setFont(QFont("Courier", 9))
        log_vbox.addWidget(self.log_edit)
        root.addWidget(log_group)

    # ── Panneau gauche ────────────────────────────────────────────────
    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(380)
        vbox = QVBoxLayout(panel)
        vbox.setSpacing(8)

        # --- Groupe : Paramètres ---
        grp = QGroupBox("Paramètres")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Barcode
        self.inp_barcode = QLineEdit()
        self.inp_barcode.setPlaceholderText("ex : 081227819781")
        form.addRow("Barcode * :", self.inp_barcode)

        # Dossier audio + bouton Browse
        folder_w = QWidget()
        folder_h = QHBoxLayout(folder_w)
        folder_h.setContentsMargins(0, 0, 0, 0)
        self.inp_folder = QLineEdit("/home/jm/Audio/MP3/")
        btn_browse = QPushButton("…")
        btn_browse.setFixedWidth(36)
        btn_browse.clicked.connect(self._browse_folder)
        folder_h.addWidget(self.inp_folder)
        folder_h.addWidget(btn_browse)
        form.addRow("Dossier audio :", folder_w)

        # Niveau de log
        self.cmb_loglevel = QComboBox()
        self.cmb_loglevel.addItems(["INFO", "DEBUG", "WARNING", "ERROR"])
        form.addRow("Niveau de log :", self.cmb_loglevel)

        # Compositeur
        self.chk_compositeur = QCheckBox("Ajouter le compositeur au titre")
        form.addRow("", self.chk_compositeur)

        # Genre
        self.inp_genre = QLineEdit()
        self.inp_genre.setPlaceholderText("(optionnel)")
        form.addRow("Genre :", self.inp_genre)

        # Release ID
        self.inp_release = QLineEdit()
        self.inp_release.setPlaceholderText("ex : 30305858 ou [r30305858]")
        form.addRow("Release ID :", self.inp_release)

        # Interprète
        self.inp_interprete = QLineEdit()
        self.inp_interprete.setPlaceholderText("(optionnel)")
        form.addRow("Interprète :", self.inp_interprete)

        # Titre de l'album (optionnel : sinon titre Discogs)
        self.inp_album = QLineEdit()
        self.inp_album.setPlaceholderText("(optionnel – sinon titre Discogs)")
        form.addRow("Titre album :", self.inp_album)

        # Discogs Token
        self.inp_token = QLineEdit()
        self.inp_token.setPlaceholderText("(demandé au lancement si vide)")
        self.inp_token.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Discogs Token :", self.inp_token)

        grp.setLayout(form)
        vbox.addWidget(grp)

        # --- Boutons action ---
        self.btn_run = QPushButton("▶  Exécuter Tagger")
        self.btn_run.setFixedHeight(38)
        self.btn_run.setStyleSheet(
            "QPushButton          { background:#4CAF50; color:#fff; font-weight:bold;"
            "                       border-radius:5px; font-size:13px; }"
            "QPushButton:hover    { background:#45a049; }"
            "QPushButton:disabled { background:#aaa; color:#ccc; }"
        )
        self.btn_run.clicked.connect(self._run_tagger)
        vbox.addWidget(self.btn_run)

        btn_refresh = QPushButton("↻  Rafraîchir tableau")
        btn_refresh.setFixedHeight(32)
        btn_refresh.clicked.connect(self._refresh_table)
        vbox.addWidget(btn_refresh)

        # --- Groupe : Images album ---
        img_grp = QGroupBox("Images album")
        img_vbox = QVBoxLayout(img_grp)
        img_vbox.setContentsMargins(4, 4, 4, 4)

        self._scroll_images = QScrollArea()
        self._scroll_images.setWidgetResizable(True)
        self._images_container = QWidget()
        self._images_grid = QGridLayout(self._images_container)
        self._images_grid.setSpacing(4)
        self._scroll_images.setWidget(self._images_container)
        img_vbox.addWidget(self._scroll_images)

        img_grp.setLayout(img_vbox)
        vbox.addWidget(img_grp, stretch=1)
        return panel

    # ── Panneau droit ─────────────────────────────────────────────────
    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        vbox = QVBoxLayout(panel)
        vbox.setSpacing(4)

        # Titre
        vbox.addWidget(_make_label("Pistes audio", size=12, bold=True))

        # Tableau
        headers = ["Fichier", "N°", "Titre", "Artiste", "Album", "Genre", "Qualité"]
        self.table = QTableWidget()
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)

        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Fichier
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # N°
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Titre
        for c in (3, 4, 5, 6):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)

        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        vbox.addWidget(self.table)

        # Légende : du pire (rouge) au meilleur (vert)
        legend = QWidget()
        lh = QHBoxLayout(legend)
        lh.setContentsMargins(0, 2, 0, 2)
        lh.addWidget(_make_label("Qualité :"))
        for _, label, bg, _ in reversed(_QUALITY_LEVELS):
            swatch = QLabel()
            swatch.setFixedSize(14, 14)
            swatch.setStyleSheet(
                f"background:{bg}; border:1px solid #888; border-radius:2px;"
            )
            lh.addWidget(swatch)
            lh.addWidget(_make_label(label, size=9))
            lh.addSpacing(6)
        lh.addStretch()
        vbox.addWidget(legend)

        return panel

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    def _browse_folder(self):
        cur = self.inp_folder.text()
        path = QFileDialog.getExistingDirectory(
            self, "Choisir le dossier audio", cur if os.path.isdir(cur) else ""
        )
        if path:
            self.inp_folder.setText(path)

    def _build_args(self) -> list[str] | None:
        barcode = self.inp_barcode.text().strip()
        if not barcode:
            self._append_log(
                "<b style='color:red'>Erreur : le barcode est obligatoire.</b>"
            )
            return None

        args = [
            barcode,
            "-f",
            self.inp_folder.text().strip(),
            "--loglevel",
            self.cmb_loglevel.currentText(),
        ]
        if self.chk_compositeur.isChecked():
            args.append("-c")
        if g := self.inp_genre.text().strip():
            args.extend(["-g", g])
        if r := self.inp_release.text().strip():
            args.extend(["-r", r])
        if i := self.inp_interprete.text().strip():
            args.extend(["-i", i])
        if a := self.inp_album.text().strip():
            args.extend(["-a", a])
        return args

    # ── Exécution ─────────────────────────────────────────────────────
    def _run_tagger(self):
        args = self._build_args()
        if args is None:
            return

        # Token Discogs : 1) champ du formulaire, 2) variable d'environnement
        # TOKEN_DISCOGS (optionnelle), 3) boîte de dialogue de saisie
        token = self.inp_token.text().strip()
        if not token:
            # token = os.environ.get("TOKEN_DISCOGS", "").strip()
            token = ( os.environ.get("DISCOGS_TOKEN", "") or os.environ.get("TOKEN_DISCOGS", "")).strip()
        if not token:
            token, ok = QInputDialog.getText(
                self,
                "Token Discogs",
                "Saisissez votre token Discogs :\n"
                "(https://www.discogs.com/settings/developers)",
                QLineEdit.EchoMode.Password,
            )
            token = token.strip()
            if not ok or not token:
                self._append_log(
                    "<b style='color:red'>Erreur : le token Discogs est obligatoire.</b>"
                )
                return
            # Mémorisé dans le champ pour les exécutions suivantes (session en cours)
            self.inp_token.setText(token)

        self.btn_run.setEnabled(False)
        self.log_edit.clear()
        self._append_log("<b style='color:#2196F3'>▶ Démarrage du tagger…</b>")

        # Environnement : on propage le token via une var env
        env = os.environ.copy()
        env["DISCOGS_TOKEN"] = token

        self._worker = _TaggerWorker(args, self._script_path, env=env)
        self._worker.log_line.connect(self._on_log_line)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_log_line(self, line: str):
        esc = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        if "- ERROR -" in line:
            color = "#e53935"
        elif "- WARNING -" in line:
            color = "#fb8c00"
        elif "- DEBUG -" in line:
            color = "#757575"
        elif line.startswith("[CMD]"):
            color = "#2196F3"
        else:
            color = "#212121"

        self.log_edit.append(f"<span style='color:{color}'>{esc}</span>")

    def _on_finished(self, rc: int):
        self.btn_run.setEnabled(True)
        if rc == 0:
            self._append_log("<b style='color:#4CAF50'>✓ Terminé avec succès.</b>")
        else:
            self._append_log(
                f"<b style='color:#e53935'>✗ Terminé avec erreur (code {rc}).</b>"
            )
        # Rafraîchir tableau et images automatiquement après exécution
        self._refresh_table()
        self._refresh_images()

    # ── Tableau ───────────────────────────────────────────────────────
    def _refresh_table(self):
        folder = self.inp_folder.text().strip()
        self.table.setRowCount(0)
        if not folder or not os.path.isdir(folder):
            return

        tracks = _collect_tracks(folder)
        self.table.setRowCount(len(tracks))

        for row, track in enumerate(tracks):
            # Colonnes 0-5 : fichier, N°, titre, artiste, album, genre
            for col, val in enumerate(
                [
                    track["filename"],
                    track["tracknumber"],
                    track["title"],
                    track["artist"],
                    track["album"],
                    track["genre"],
                ]
            ):
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col == 0:
                    item.setToolTip(track["path"])  # chemin complet en tooltip
                self.table.setItem(row, col, item)

            # Colonne 6 : qualité avec code couleur
            label, bg, fg = track["quality"]
            q_item = QTableWidgetItem(label)
            q_item.setFlags(q_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            q_item.setBackground(QColor(bg))
            q_item.setForeground(QColor(fg))
            self.table.setItem(row, 6, q_item)

    # ── Images ────────────────────────────────────────────────────────
    def _refresh_images(self):
        # Vider les images précédentes
        while self._images_grid.count():
            w = self._images_grid.takeAt(0).widget()
            if w:
                w.deleteLater()

        folder = self.inp_folder.text().strip()
        if not folder or not os.path.isdir(folder):
            return

        img_exts = (".jpg", ".jpeg", ".png", ".bmp", ".gif")
        img_files = sorted(
            f for f in os.listdir(folder) if f.lower().endswith(img_exts)
        )

        if not img_files:
            lbl = QLabel("Aucune image trouvée dans le dossier")
            lbl.setStyleSheet("color:#999; font-style:italic;")
            self._images_grid.addWidget(lbl, 0, 0)
            return

        COLS = 3
        for idx, name in enumerate(img_files):
            full_path = os.path.join(folder, name)
            pix = QPixmap(full_path)
            if pix.isNull():
                continue
            thumb = pix.scaled(
                QSize(110, 110),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            lbl = _ClickableLabel(full_path)
            lbl.setPixmap(thumb)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setToolTip(f"{name}\n(cliquez pour ouvrir)")
            lbl.setStyleSheet(
                "_ClickableLabel { border:1px solid #ccc; border-radius:4px;"
                " padding:2px; background:#fff; }"
                " _ClickableLabel:hover { border-color:#2196F3; }"
            )
            lbl.clicked.connect(self._open_image_viewer)
            self._images_grid.addWidget(lbl, idx // COLS, idx % COLS)

    # ── Visionneuse image ─────────────────────────────────────────────
    def _open_image_viewer(self, image_path: str):
        """Ouvre l'image dans une fenêtre séparée, redimensionnée pour l'écran."""
        pix = QPixmap(image_path)
        if pix.isNull():
            return

        # Géométrie disponible de l'écran principal
        screen_geom = QApplication.primaryScreen().availableGeometry()
        max_w = screen_geom.width() - 40
        max_h = screen_geom.height() - 40

        # Scale l'image pour entrer dans l'écran en préservant le rapport
        pix = pix.scaled(
            QSize(max_w, max_h),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        # Fenêtre modale
        viewer = QDialog(self)
        viewer.setWindowTitle(os.path.basename(image_path))
        viewer.setWindowFlag(Qt.WindowType.Window)

        layout = QVBoxLayout(viewer)
        layout.setContentsMargins(0, 0, 0, 0)

        img_label = QLabel()
        img_label.setPixmap(pix)
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(img_label)

        viewer.resize(pix.width() + 4, pix.height() + 4)
        viewer.exec()

    # ── Helper ────────────────────────────────────────────────────────
    def _append_log(self, html: str):
        self.log_edit.append(html)


# ---------------------------------------------------------------------------
# Fonctions utilitaires (hors classe)
# ---------------------------------------------------------------------------
def _collect_tracks(folder: str) -> list[dict]:
    """Lit tous les fichiers MP3 du dossier et retourne la liste triée par piste."""
    tracks: list[dict] = []

    for root, _, files in os.walk(folder):
        for fname in files:
            if not fname.lower().endswith(".mp3"):
                continue

            fp = os.path.join(root, fname)
            info: dict = {"path": fp, "filename": fname}

            # Tags via EasyID3
            try:
                tags = EasyID3(fp)
                for key in ("tracknumber", "title", "artist", "album", "genre"):
                    vals = tags.get(key)
                    info[key] = vals[0] if vals else ""
            except Exception:
                for key in ("tracknumber", "title", "artist", "album", "genre"):
                    info.setdefault(key, "")

            # Clé de tri numérique (gère le format "3/12")
            try:
                info["_sort"] = int(info["tracknumber"].split("/")[0])
            except (ValueError, AttributeError):
                info["_sort"] = 0

            # Analyse qualité audio
            info["quality"] = _analyze_quality(fp)

            tracks.append(info)

    tracks.sort(key=lambda t: t["_sort"])
    return tracks


def _read_tagger_version(script_path: str) -> str:
    """Lit la variable VERSION de tagger.py sans l'importer (retourne "" si introuvable)."""
    try:
        with open(script_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = re.match(r"""\s*VERSION\s*=\s*['"]([^'"]+)['"]""", line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return ""


def _analyze_quality(filepath: str) -> tuple[str, str, str]:
    """Retourne (label, bg_hex, fg_hex) pour un fichier MP3."""
    try:
        audio = MP3(filepath)
        if hasattr(audio, "info") and hasattr(audio.info, "bitrate"):
            return _evaluate_quality(audio.info.bitrate / 1000)
    except Exception:
        pass
    return "N/A", "#cccccc", "#333333"


def _make_label(text: str, size: int = 10, bold: bool = False) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont("Sans", size, QFont.Weight.Bold if bold else QFont.Weight.Normal))
    return lbl


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Icône de l'application (img/ à la racine du projet)
    icon_path = os.path.normpath(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "..",
            "img",
            "icone2.png",
        )
    )
    app.setWindowIcon(QIcon(icon_path))
    app.setStyleSheet(
        """
        QGroupBox {
            font-weight: bold;
            border: 1px solid #bbb;
            border-radius: 6px;
            margin-top: 12px;
            padding-top: 4px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 6px;
            color: #333;
        }
        QLineEdit, QComboBox {
            padding: 3px 6px;
            border: 1px solid #ccc;
            border-radius: 4px;
        }
        QLineEdit:focus, QComboBox:focus {
            border-color: #2196F3;
        }
        QTableWidget {
            border: 1px solid #ccc;
        }
        QTableWidget::item {
            padding: 3px 6px;
        }
    """
    )

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
