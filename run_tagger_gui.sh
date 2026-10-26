#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_tagger_gui.sh – Lance l'application tagger_gui dans son venv isolé.
#
#   1. Charge pyenv depuis ~/.bash_profile
#   2. Active le virtualenv venv_tagger (Python 3.11.13)
#   3. Installe les dépendances (requirements.txt) si nécessaire
#   4. Lance src/gui/tagger_gui.py
#
# Option : TOKEN_DISCOGS="votre_token" ./run_tagger_gui.sh  (évite la saisie du token)
# ---------------------------------------------------------------------------
set -euo pipefail

# ── Résolution du répertoire du projet (même si lancé depuis ailleurs) ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_NAME="venv_tagger"
PYTHON_VERSION="3.11.13"
VENV_PYTHON="${HOME}/.pyenv/versions/${PYTHON_VERSION}/envs/${VENV_NAME}/bin/python"
VENV_PIP="${HOME}/.pyenv/versions/${PYTHON_VERSION}/envs/${VENV_NAME}/bin/pip"

# ── 1. Charge pyenv ──────────────────────────────────────────────────────
if [ -f "${HOME}/.bash_profile" ]; then
    set +u
    # shellcheck source=/dev/null
    source "${HOME}/.bash_profile"
    set -u
fi

# ── 2. Vérifie que le venv existe ─────────────────────────────────────────
if [ ! -x "$VENV_PYTHON" ]; then
    echo "[ERREUR] Le virtualenv '${VENV_NAME}' introuvable."
    echo "         Créez-le avec : pyenv virtualenv ${PYTHON_VERSION} ${VENV_NAME}"
    exit 1
fi

echo "[INFO] Python utilisé : $($VENV_PYTHON --version) — ${VENV_PYTHON}"

# ── 3. Installation conditionnelle des dépendances ───────────────────────
# On compare requirements.txt avec un fichier stamp (.pip_installed) créé
# à chaque installation réussie. Si le stamp est plus ancien que
# requirements.txt (ou s'il n'existe pas), on réinstalle.
STAMP_FILE="${SCRIPT_DIR}/.pip_installed"

if [ ! -f "$STAMP_FILE" ] || [ "$SCRIPT_DIR/requirements.txt" -nt "$STAMP_FILE" ]; then
    echo "[INFO] Installation des dépendances depuis requirements.txt …"
    "$VENV_PIP" install -r requirements.txt
    touch "$STAMP_FILE"
    echo "[INFO] Dépendances installées avec succès."
else
    echo "[INFO] Dépendances déjà à jour (stamp : $(date -r "$STAMP_FILE"))."
fi

# ── 4. Lance l'application ────────────────────────────────────────────────
echo "[INFO] Démarrage de tagger_gui …"
# Le token Discogs n'est plus défini ici. Il est optionnel : si la variable
# d'environnement TOKEN_DISCOGS est renseignée au lancement, elle est utilisée
# (aucune boîte de dialogue), sinon l'application demande le token.
#   Exemple :  TOKEN_DISCOGS="xxxxxxxx" ./run_tagger_gui.sh
exec "$VENV_PYTHON" src/gui/tagger_gui.py "$@"
