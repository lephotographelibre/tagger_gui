#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_tagger.sh – Lance tagger.py (mode ligne de commande) dans son venv isolé.
#
#   1. Charge pyenv depuis ~/.bash_profile
#   2. Utilise le virtualenv venv_tagger (Python 3.11.13)
#   3. Installe les dépendances (requirements.txt) si nécessaire
#   4. Lance src/tagger.py en lui transmettant tous les arguments
#
# Exemples :
#   ./run_tagger.sh --help
#   ./run_tagger.sh <arguments de tagger.py>
#   TOKEN_DISCOGS="votre_token" ./run_tagger.sh <arguments>   (évite la saisie du token)
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
    echo "[ERREUR] Le virtualenv '${VENV_NAME}' est introuvable." >&2
    echo "         Créez-le avec : pyenv virtualenv ${PYTHON_VERSION} ${VENV_NAME}" >&2
    exit 1
fi

# Les messages [INFO] vont sur la sortie d'erreur pour ne pas polluer
# la sortie normale de tagger.py (utile si vous la redirigez vers un fichier).
echo "[INFO] Python utilisé : $($VENV_PYTHON --version) — ${VENV_PYTHON}" >&2

# ── 3. Installation conditionnelle des dépendances ───────────────────────
# On compare requirements.txt avec un fichier stamp (.pip_installed) créé
# à chaque installation réussie. Si le stamp est plus ancien que
# requirements.txt (ou s'il n'existe pas), on réinstalle.
# Ce stamp est le même que celui de run_tagger_gui.sh : les deux scripts
# partagent le même venv, donc l'installation n'est faite qu'une seule fois.
STAMP_FILE="${SCRIPT_DIR}/.pip_installed"

if [ ! -f "$STAMP_FILE" ] || [ "$SCRIPT_DIR/requirements.txt" -nt "$STAMP_FILE" ]; then
    echo "[INFO] Installation des dépendances depuis requirements.txt …" >&2
    "$VENV_PIP" install -r requirements.txt >&2
    touch "$STAMP_FILE"
    echo "[INFO] Dépendances installées avec succès." >&2
else
    echo "[INFO] Dépendances déjà à jour (stamp : $(date -r "$STAMP_FILE"))." >&2
fi

# ── 4. Lance l'application ────────────────────────────────────────────────
echo "[INFO] Démarrage de tagger …" >&2
# Le token Discogs est optionnel ici : si la variable d'environnement
# TOKEN_DISCOGS est renseignée au lancement, elle est utilisée ; sinon
# tagger.py le demande (boîte de dialogue, ou saisie dans le terminal).
exec "$VENV_PYTHON" src/tagger.py "$@"
