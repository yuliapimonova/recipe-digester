# Builds the downloadable app: pyinstaller recipe-digester.spec
# macOS gets "Recipe Digester.app", Windows a "Recipe Digester" folder with Recipe Digester.exe.
import sys

from PyInstaller.utils.hooks import copy_metadata

# Ship every bundled library's metadata, which holds its license text, as their licenses require.
requirements = [line.strip() for line in open("requirements.txt") if line.strip()]
licenses = [item for name in requirements for item in copy_metadata(name, recursive=True)]

a = Analysis(["app.py"], datas=[("static", "static"), *licenses])
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Recipe Digester",
    console=False,
    icon="static/icon.png",
)
app_folder = COLLECT(exe, a.binaries, a.datas, name="Recipe Digester")
if sys.platform == "darwin":
    app = BUNDLE(
        app_folder,
        name="Recipe Digester.app",
        icon="static/icon.png",
        bundle_identifier="org.recipe-digester.app",
        info_plist={"NSHighResolutionCapable": True},
    )
