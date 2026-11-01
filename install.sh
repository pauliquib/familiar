#!/bin/sh
# Instalace familiara z tohoto repozitáře: balíček, pak `familiar install`.
#
#   sh install.sh [--autostart] [--dry-run]     volby jdou do `familiar install`
#
# Balíček se instaluje jako kopie (ne editable), nainstalovaný familiar na repu
# nezávisí. Pořadí pokusů:
#   1. uv tool install (se sítí, bez ní z cache uv)
#   2. pipx install (jen se sítí)
#   3. jinak: venv se systémovými balíčky, PySide6 a tomlkit z site-packages python3
#      (~/.local/lib/python3.* nebo systémové), pip bez sítě a bez kontroly metadat
# `familiar install` pak atomicky přesměruje ~/.local/bin/familiar{,-emit}
# a doplní hooky; hooky tak nikdy nevolají chybějící emitter.
set -eu

repo=$(cd "$(dirname "$0")" && pwd -P)
data="${XDG_DATA_HOME:-$HOME/.local/share}/familiar"

case " $* " in
    *" --dry-run "*)
        echo "nanečisto: uv tool install --reinstall-package familiar $repo"
        PYTHONPATH="$repo" exec python3 -m familiar install --source "$repo" --via uv "$@" ;;
esac

# rychlá kontrola sítě: bez ní by pip/pipx čekaly na časové limity minuty
online=0
python3 -c "import socket; socket.create_connection(('pypi.org', 443), 3).close()" 2>/dev/null && online=1
export UV_HTTP_TIMEOUT=10 PIP_DEFAULT_TIMEOUT=5 PIP_RETRIES=0

venv=
via=
if command -v uv >/dev/null 2>&1; then
    # --force jen poprvé (přepíše starý odkaz do repa atomicky); u aktualizace by
    # --force smazal celé prostředí a emitter by na chvíli chyběl
    force=--force
    [ -d "$(uv tool dir)/familiar" ] && force=
    offline=
    [ "$online" = 1 ] || offline=--offline
    # --reinstall-package: vždy znovu sestavit z aktuálních zdrojů
    uv_install() { uv tool install "$@" --reinstall-package familiar "$repo"; }
    # další pokus jen, když se od předchozího liší (bez sítě by se jinak opakoval stejný)
    if uv_install $force $offline \
        || { [ -z "$offline" ] && uv_install $force --offline; } \
        || { [ -z "$force" ] && uv_install --force --offline; }; then
        via=uv
        venv="$(uv tool dir)/familiar"
    fi
fi
if [ -z "$via" ] && [ "$online" = 1 ] && command -v pipx >/dev/null 2>&1; then
    if pipx install --force "$repo"; then
        via=pipx
        venv="$(pipx environment --value PIPX_LOCAL_VENVS)/familiar"
    fi
fi
if [ -z "$via" ]; then
    echo "uv ani pipx nejdou, instaluji bez sítě do venv se systémovými balíčky" >&2
    venv="$data/venv-$(date +%Y%m%d%H%M%S)"
    python3 -m venv --system-site-packages "$venv"
    # závislosti z site-packages python3 (uživatelských i systémových); kontrola importem,
    # ne metadaty: PySide6 z balíčku distribuce se nejmenuje PySide6-Essentials
    if ! "$venv/bin/python" -c "import sys, PySide6.QtWidgets, PySide6.QtDBus, tomlkit
sys.exit(PySide6.__version_info__ < (6, 5))" 2>/dev/null; then
        rm -rf -- "$venv"
        echo "CHYBA: bez sítě potřebuju PySide6 >= 6.5 a tomlkit pro $(python3 -V)" \
            "(např. v ~/.local/lib/python3.*/site-packages), nebo uv s nimi v cache" >&2
        exit 1
    fi
    "$venv/bin/python" -m pip install -q --no-index --no-deps --disable-pip-version-check "$repo"
    # -I: bez uživatelských .pth souborů, jinak by hook trval přes 30 ms
    # (shebang, nebo u dlouhé cesty spouštěč přes /bin/sh s exec na 2. řádku)
    sed -i -e '1s|^\(#!/.*/python[0-9.]*\)$|\1 -I|' -e "2s|^'''exec' \([^ ]*\) |'''exec' \1 -I |" \
        "$venv/bin/familiar-emit"
    via=venv
fi

# nainstalovaný familiar přímo z jeho prostředí, ne první z PATH
"$venv/bin/familiar" install --source "$repo" --via "$via" "$@"

# staré záložní prostředí (odkazy už vedou jinam)
for old in "$data"/venv-*; do
    [ -d "$old" ] && [ "$old" != "$venv" ] && rm -rf -- "$old"
done
exit 0
