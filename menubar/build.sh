#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "Building Chikki menu bar app..."
swift build -c release 2>&1

# Create .app bundle
APP_DIR="build/Chikki.app/Contents"
mkdir -p "$APP_DIR/MacOS"
mkdir -p "$APP_DIR/Resources"

cp .build/release/ChikkiApp "$APP_DIR/MacOS/Chikki"
cp Sources/Info.plist "$APP_DIR/Info.plist"

echo ""
echo "Built: $(pwd)/build/Chikki.app"
echo ""
echo "To run:"
echo "  open build/Chikki.app"
echo ""
echo "To run on login:"
echo "  1. Open System Settings > General > Login Items"
echo "  2. Add build/Chikki.app"
echo ""
echo "Or copy to /Applications:"
echo "  cp -r build/Chikki.app /Applications/"
