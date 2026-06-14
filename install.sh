#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "🍫 Scribe — Setup"
echo ""

# ── Prerequisites ──────────────────────────────────────────────────────────────

check_command() {
    if ! command -v "$1" &>/dev/null; then
        echo "❌  '$1' not found. $2"
        exit 1
    fi
}

echo "[1/5] Checking prerequisites..."
check_command conda "Install Miniconda: https://docs.conda.io/en/latest/miniconda.html"
# The menu bar app is built with xcodebuild and requires full Xcode (not just CLT).
check_command xcodebuild "Install full Xcode from the App Store (Command Line Tools alone are not enough)."
brew install portaudio ffmpeg 2>/dev/null || true
echo "  ✓ Prerequisites OK"

# ── Conda env ─────────────────────────────────────────────────────────────────

echo ""
echo "[2/5] Setting up conda environment 'scribe'..."
if conda info --envs 2>/dev/null | grep -q "^scribe "; then
    echo "  Updating existing 'scribe' env..."
    conda env update -f environment.yml --prune -q
else
    echo "  Creating 'scribe' env..."
    conda env create -f environment.yml -q
fi
echo "  ✓ Conda env ready"

# ── Pip deps ──────────────────────────────────────────────────────────────────

echo ""
echo "[3/5] Installing Python dependencies..."
eval "$(conda shell.bash hook)"
conda activate scribe
pip install -q -r requirements.txt
echo "  ✓ Python deps installed"

# ── Config files ──────────────────────────────────────────────────────────────

echo ""
echo "[4/5] Setting up config..."

if [ ! -f "config.yaml" ]; then
    cp config.yaml.example config.yaml
    echo "  Created config.yaml from example"
else
    echo "  config.yaml already exists — skipping"
fi

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "  Created .env from example"
    echo ""
    echo "  ⚠️  Open .env and add your API key:"
    echo "       GOOGLE_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY"
    echo "       (match the provider set in config.yaml)"
else
    echo "  .env already exists — skipping"
fi

# ── Swift app ────────────────────────────────────────────────────────────────

echo ""
echo "[5/5] Building Scribe menu bar app..."
cd menubar && bash build.sh
cd "$SCRIPT_DIR"

# ── Done ─────────────────────────────────────────────────────────────────────

echo ""
echo "✅  Setup complete!"
echo ""
echo "Next steps:"
echo ""
echo "  1. Edit .env and add your API key"
echo "  2. conda activate scribe"
echo "  3. python -m src.cli quick         # record + transcribe + summarize"
echo "  4. open menubar/build/Scribe.app  # launch menu bar app"
echo ""
echo "Optional alias (add to ~/.zshrc):"
echo "  alias scribe='conda activate scribe && cd $SCRIPT_DIR && python -m src.cli'"
