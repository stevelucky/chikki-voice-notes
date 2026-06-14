"""Global hotkey helper for Scribe.

Creates a macOS AppleScript that can be bound to a keyboard shortcut.
Run: python -m src.cli menubar  for the full menu bar experience.
"""

import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.resolve()


def setup_shortcut():
    """Create an AppleScript helper that can be bound to a keyboard shortcut via macOS Settings."""
    script = f'''
    tell application "Terminal"
        do script "cd {_PROJECT_ROOT} && conda activate scribe && python -m src.cli quick"
        activate
    end tell
    '''

    bin_dir = _PROJECT_ROOT / "bin"
    bin_dir.mkdir(exist_ok=True)
    helper_path = bin_dir / "scribe-quick.scpt"

    subprocess.run(
        ["osacompile", "-o", str(helper_path), "-e", script],
        check=True,
    )
    print(f"AppleScript saved to: {helper_path}")
    print()
    print("To bind to a keyboard shortcut:")
    print("  1. Open System Settings > Keyboard > Keyboard Shortcuts > Services")
    print("  2. Or use Automator to create a Quick Action with this script")
    print("  3. Assign Cmd+Shift+R (or your preferred hotkey)")
    print()
    print("Alternatively, just run: python -m src.cli menubar")


if __name__ == "__main__":
    setup_shortcut()
