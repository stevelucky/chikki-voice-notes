#!/bin/bash
set -e

cd "$(dirname "$0")"

export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer

echo "Building Chikki..."
xcodebuild -scheme ChikkiApp \
    -configuration Release \
    -derivedDataPath .xcode-build \
    -destination "platform=macOS" \
    build 2>&1 | grep -E "error:|warning:|BUILD"

BINARY=".xcode-build/Build/Products/Release/ChikkiApp"

# Create .app bundle
rm -rf build/Chikki.app
mkdir -p build/Chikki.app/Contents/MacOS
mkdir -p build/Chikki.app/Contents/Resources

cp "$BINARY" build/Chikki.app/Contents/MacOS/Chikki
cp Sources/Info.plist build/Chikki.app/Contents/Info.plist

# Copy resource bundles from dependencies (e.g. KeyboardShortcuts localizations)
for bundle in .xcode-build/Build/Products/Release/*.bundle; do
    [ -d "$bundle" ] && cp -r "$bundle" build/Chikki.app/Contents/Resources/
done

# Ad-hoc sign so Gatekeeper allows it to run
codesign --force --deep --sign - build/Chikki.app

echo ""
echo "Built: $(pwd)/build/Chikki.app"

if [ "${1}" = "--install" ]; then
    cp -r build/Chikki.app /Applications/
    echo "Installed to /Applications/Chikki.app"
    open /Applications/Chikki.app
fi

echo ""
echo "Usage:"
echo "  ./build.sh            # build only"
echo "  ./build.sh --install  # build + copy to /Applications + launch"
echo ""
echo "To start on login:"
echo "  System Settings > General > Login Items & Extensions > +"
echo "  Add /Applications/Chikki.app"
