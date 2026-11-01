# Minimální PEP 517 backend: wheel a sdist jen ze standardní knihovny.
#
# Build tak funguje offline (pip ani uv nemusí nic stahovat). Editable
# instalaci záměrně nenabízí: nainstalovaný familiar nesmí záviset na repu.
import base64, hashlib, io, os, re, tarfile, tomllib, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = "familiar"
SKIP = (".pyc", ".pyo")   # do balíčku jde vše z familiar/ kromě těchto a __pycache__
EXTRAS = {"extras/gnome-shell": "familiar/gnome_shell"}    # mimo balíček v repu, ve wheelu uvnitř

# familiar-emit běží v každém hooku Claude Code. Console script z [project.scripts] by spustil
# Python se site (.pth soubory, u uv i _virtualenv → contextlib): ~8 ms navíc. Argumenty
# v shebangu `#!python` instalátory (uv, pip) zahodí a u dlouhé cesty z něj dělají trampolínu
# přes sh. Proto vlastní skript v .data/scripts, který instalátor zkopíruje beze změny: sh najde
# python3 prostředí vedle skutečného souboru a spustí ho s -I -S; Python pak přidá jen
# site-packages prostředí.
# Při jakékoli poruše (chybí realpath, python, balíček, vadný interpret) nic nevypíše, dočte
# stdin (zapisující Claude nesmí dostat EPIPE) a skončí 0. Proto python jako potomek, ne exec
# (selhaný exec ukončí sh s kódem 126; potomek stojí ~0,4 ms). pid Claude Code (rodič sh)
# dostane Python v --ppid, jeho rodičem je teď sh.
EMIT_LAUNCHER = """#!/bin/sh
# familiar-emit: hook Claude Code -> familiard (familiar/emit.py). Nic nevypíše, vždy exit 0.
# Soubor je pro sh i Python: sh spustí python3 svého prostředí s -I -S (bez site).
''':'
exec 2>/dev/null
p=$0
case $p in -*) p=./$p ;; esac
p=$(realpath "$p" || readlink -f "$p") || p=$0
"${p%/*}/python3" -I -S "$p" --ppid="$PPID" "$@" || { cat || while read -r _; do :; done; } >/dev/null
exit 0
'''
import sys
ppid = None
if sys.argv[1:2] and sys.argv[1].startswith("--ppid="):
    ppid = sys.argv.pop(1)[7:]
try:
    sys.path.append(f"{sys.prefix}/lib/python{sys.version_info[0]}.{sys.version_info[1]}/site-packages")
    try:
        from familiar.emit import main
    except ImportError:     # jiné rozvržení prostředí: najde ho site (pomalejší, ale funguje)
        import site
        site.main()
        from familiar.emit import main
except BaseException:
    try:                    # dočíst stdin, i když balíček chybí
        import posix
        while posix.read(0, 1 << 18):
            pass
    except BaseException:
        pass
    sys.exit(0)
main(ppid)
"""
LAUNCHERS = {"familiar-emit": EMIT_LAUNCHER}    # nahrazují stejnojmenné [project.scripts]


def _project():
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
        proj = tomllib.load(f)["project"]
    with open(os.path.join(ROOT, PACKAGE, "__init__.py")) as f:
        proj["version"] = re.search(r'^__version__ = "([^"]+)"', f.read(), re.M).group(1)
    return proj


def _metadata(proj):
    lines = ["Metadata-Version: 2.4", f"Name: {proj['name']}", f"Version: {proj['version']}",
             f"Summary: {proj['description']}", f"License-Expression: {proj['license']}",
             f"Requires-Python: {proj['requires-python']}"]
    lines += [f"License-File: {p}" for p in proj.get("license-files", ())]
    lines += [f"Requires-Dist: {d}" for d in proj.get("dependencies", ())]
    return "\n".join(lines) + "\n"


def _files(wheel=False):
    """(cesta, jméno v archivu); ve wheelu jdou EXTRAS do balíčku (nainstalovaný familiar je najde)."""
    for src in (PACKAGE, *EXTRAS):
        for base, dirs, files in os.walk(os.path.join(ROOT, src)):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for name in sorted(files):
                if not name.endswith(SKIP):
                    path = os.path.join(base, name)
                    arc = os.path.relpath(path, ROOT)
                    if wheel and src in EXTRAS:
                        arc = EXTRAS[src] + arc[len(src):]
                    yield path, arc


def _dist(proj):
    return f"{proj['name'].replace('-', '_')}-{proj['version']}"


def get_requires_for_build_wheel(config_settings=None):
    return []


def get_requires_for_build_sdist(config_settings=None):
    return []


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    proj = _project()
    dist = _dist(proj)
    info = f"{dist}.dist-info"
    scripts = "".join(f"{k} = {v}\n" for k, v in proj.get("scripts", {}).items() if k not in LAUNCHERS)
    extra = {
        f"{info}/METADATA": _metadata(proj),
        f"{info}/WHEEL": "Wheel-Version: 1.0\nGenerator: familiar_build\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        f"{info}/entry_points.txt": "[console_scripts]\n" + scripts,
    }
    name = f"{dist}-py3-none-any.whl"
    record = []
    with zipfile.ZipFile(os.path.join(wheel_directory, name), "w", zipfile.ZIP_DEFLATED) as z:
        def add(arc, data, mode=0o644):
            zi = zipfile.ZipInfo(arc, (2020, 1, 1, 0, 0, 0))
            zi.external_attr = (0o100000 | mode) << 16   # skript musí být spustitelný
            z.writestr(zi, data)
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            record.append(f"{arc},sha256={digest},{len(data)}")
        for path, arc in _files(wheel=True):
            with open(path, "rb") as f:
                add(arc, f.read())
        for p in proj.get("license-files", ()):
            with open(os.path.join(ROOT, p), "rb") as f:
                add(f"{info}/licenses/{p}", f.read())
        for script, text in LAUNCHERS.items():
            add(f"{dist}.data/scripts/{script}", text.encode(), 0o755)
        for arc, text in extra.items():
            add(arc, text.encode())
        record.append(f"{info}/RECORD,,")
        z.writestr(zipfile.ZipInfo(f"{info}/RECORD", (2020, 1, 1, 0, 0, 0)), "\n".join(record) + "\n")
    return name


def build_sdist(sdist_directory, config_settings=None):
    proj = _project()
    dist = _dist(proj)
    name = f"{dist}.tar.gz"
    files = [(os.path.join(ROOT, p), p)
             for p in ("pyproject.toml", "install.sh", "_build/familiar_build.py", *proj.get("license-files", ()))]
    with tarfile.open(os.path.join(sdist_directory, name), "w:gz") as t:
        for path, arc in files + list(_files()):
            t.add(path, f"{dist}/{arc}")
        pkg = _metadata(proj).encode()
        ti = tarfile.TarInfo(f"{dist}/PKG-INFO")
        ti.size = len(pkg)
        t.addfile(ti, io.BytesIO(pkg))
    return name
