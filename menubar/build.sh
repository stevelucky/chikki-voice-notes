#!/bin/bash
set -e

cd "$(dirname "$0")"

export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer

echo "Building Scribe..."
xcodebuild -scheme ScribeApp \
    -configuration Release \
    -derivedDataPath .xcode-build \
    -destination "platform=macOS" \
    build 2>&1 | grep -E "error:|warning:|BUILD"

BINARY=".xcode-build/Build/Products/Release/ScribeApp"

# Create .app bundle
rm -rf build/Scribe.app
mkdir -p build/Scribe.app/Contents/MacOS
mkdir -p build/Scribe.app/Contents/Resources

cp "$BINARY" build/Scribe.app/Contents/MacOS/Scribe
cp Sources/Info.plist build/Scribe.app/Contents/Info.plist

# Copy app icon
cp Scribe.icns build/Scribe.app/Contents/Resources/

# Copy resource bundles from dependencies (e.g. KeyboardShortcuts localizations)
for bundle in .xcode-build/Build/Products/Release/*.bundle; do
    [ -d "$bundle" ] && cp -r "$bundle" build/Scribe.app/Contents/Resources/
done

# Ad-hoc sign so Gatekeeper allows it to run
codesign --force --deep --sign - build/Scribe.app

echo ""
echo "Built: $(pwd)/build/Scribe.app"

if [ "${1}" = "--install" ]; then
    pkill -x Scribe 2>/dev/null || true
    pkill -f "src.cli record" 2>/dev/null || true
    sleep 0.3
    cp -r build/Scribe.app /Applications/
    echo "Installed to /Applications/Scribe.app"
    open /Applications/Scribe.app
fi

echo ""
echo "Usage:"
echo "  ./build.sh            # build only"
echo "  ./build.sh --install  # build + copy to /Applications + launch"
echo ""
echo "To start on login:"
echo "  System Settings > General > Login Items & Extensions > +"
echo "  Add /Applications/Scribe.app"
