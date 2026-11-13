#!/bin/zsh
# Installerer ugeplan-mcp med Garmin-delen på en Mac, der altid er tændt. Se docs/MAC.md.
#
#   mkdir -p ~/ugeplan-mac && cd ~/ugeplan-mac
#   curl -fsSLO https://raw.githubusercontent.com/JuliusTorpLarsenPrivat/ugeplan-mcp/main/mac/installer.zsh
#   curl -fsSLO https://raw.githubusercontent.com/JuliusTorpLarsenPrivat/ugeplan-mcp/main/mac/tjek.zsh
#   zsh installer.zsh                            # nyeste version
#   UGEPLAN_VERSION=v0.37.0 zsh installer.zsh    # en bestemt version
#
# Gør, og kan køres igen (også for at opdatere):
#   1. tjekker git (Xcode Command Line Tools) og installerer uv, hvis det mangler
#   2. uv tool install "ugeplan-mcp[garmin] @ git+…@<version>": ét miljø med begge servere
#   3. fletter "ugeplan" og "garmin" ind i Claude Desktops konfiguration (backup først)
#   4. spørger, om Claude skal starte ved login, og tjekker dvale
# Den logger ikke ind nogen steder og rører ikke nøgleringen.

set -eu

REPO="https://github.com/JuliusTorpLarsenPrivat/ugeplan-mcp"
CONFIG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
DATA="${HANDLE_MCP_DATA:-$HOME/.local/share/handle-mcp}"

trin() { print -P "\n%B== $1%b"; }
ok()   { print "   ok: $1"; }
adv()  { print "   ADVARSEL: $1"; }
stop() { print "\n   STOP: $1"; exit 1; }

[[ "$(uname -s)" == "Darwin" ]] || stop "Scriptet er til macOS."

trin "1/4 Værktøjer"
if ! xcode-select -p >/dev/null 2>&1; then
  print "   git mangler (uv bruger det til at hente fra GitHub). Kør:  xcode-select --install"
  stop "Kør scriptet igen, når installationen er færdig."
fi
ok "git: $(git --version)"
if [[ ! -x "$HOME/.local/bin/uv" ]] && ! command -v uv >/dev/null 2>&1; then
  print "   Installerer uv (https://astral.sh/uv) ..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
UV="$(command -v uv)" || stop "uv blev ikke fundet efter installationen."
ok "uv: $UV ($("$UV" --version))"

trin "2/4 ugeplan-mcp med Garmin"
VERSION="${UGEPLAN_VERSION:-$(git ls-remote --tags --refs "$REPO" 'v*' | awk -F/ '{print $NF}' | sort -t. -k1,1 -k2,2n -k3,3n | tail -1)}"
[[ -n "$VERSION" ]] || stop "kunne ikke finde en version på $REPO (net?)."
"$UV" tool install --force --quiet "ugeplan-mcp[garmin] @ git+$REPO@$VERSION"
BIN="$("$UV" tool dir --bin)"
[[ -x "$BIN/ugeplan-mcp" && -x "$BIN/garmin-mcp" ]] || stop "ugeplan-mcp og garmin-mcp blev ikke installeret i $BIN."
ok "$VERSION i $BIN (ugeplan-mcp og garmin-mcp)"
if [[ -f "$DATA/garmin-kommando.json" ]]; then
  # Fra en ældre opsætning (fx kopieret fra en anden maskine). Den vinder over Garmin-delen i
  # samme pakke og peger sikkert det forkerte sted hen, så den lægges til side.
  mv "$DATA/garmin-kommando.json" "$DATA/garmin-kommando.json.gammel"
  ok "gammel garmin-kommando.json lagt til side (.gammel); lytteren bruger nu Garmin-delen direkte"
fi

trin "3/4 Claude Desktop-konfiguration"
mkdir -p "${CONFIG:h}"
if [[ -f "$CONFIG" ]]; then
  BACKUP="$CONFIG.backup-$(date +%Y%m%d-%H%M%S)"
  cp -p "$CONFIG" "$BACKUP"
  ok "backup: $BACKUP"
fi
"$UV" run --quiet --no-project python - "$CONFIG" "$BIN" <<'PY'
import json, os, sys, tempfile

sti, bin_ = sys.argv[1:]
data = {}
if os.path.exists(sti) and os.path.getsize(sti) > 0:
    try:
        with open(sti, encoding="utf-8") as f:
            data = json.load(f)
    except ValueError as fejl:  # ugyldig JSON: stop hellere end at overskrive den
        sys.exit(f"   STOP: {sti} er ikke gyldig JSON ({fejl}). Ret den, og kør igen.")
if not isinstance(data, dict):
    sys.exit("   STOP: konfigurationen er ikke et JSON-objekt. Ret den, og kør igen.")
servere = data.setdefault("mcpServers", {})

for navn, program in (("ugeplan", "ugeplan-mcp"), ("garmin", "garmin-mcp")):
    ny = {"command": os.path.join(bin_, program), "args": []}
    gammel = servere.get(navn)
    if gammel == ny:
        print(f"   ok: {navn} er allerede sat op")
    else:
        servere[navn] = ny
        print(f"   ok: {navn} {'erstattet (den gamle står i backuppen)' if gammel else 'tilføjet'}")
for navn in sorted(set(servere) - {"ugeplan", "garmin"}):
    s = json.dumps(servere[navn])
    if "handle_mcp" in s or "ugeplan-mcp" in s or "garmin_mcp" in s or "garmin-mcp" in s:
        print(f"   ADVARSEL: '{navn}' ser ud til også at være ugeplan- eller Garmin-serveren. Fjern den, så de ikke kører to gange.")
    else:
        print(f"   ok: urørt: {navn}")

fd, tmp = tempfile.mkstemp(dir=os.path.dirname(sti), suffix=".tmp")
with os.fdopen(fd, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
os.replace(tmp, sti)
PY

trin "4/4 Altid tændt"
if [[ -d /Applications/Claude.app ]]; then
  if osascript -e 'tell application "System Events" to get the name of every login item' 2>/dev/null | grep -q "Claude"; then
    ok "Claude starter ved login"
  else
    read "svar?   Skal Claude starte ved login? [J/n] " || svar=""
    if [[ "$svar" != [nN]* ]]; then
      osascript -e 'tell application "System Events" to make login item at end with properties {path:"/Applications/Claude.app", hidden:false}' >/dev/null \
        && ok "Claude starter nu ved login" \
        || adv "kunne ikke (giv Terminal lov under Automatisering), eller sæt det i Systemindstillinger > Generelt > Login-emner"
    fi
  fi
else
  adv "Claude-appen ligger ikke i /Applications. Installér den fra claude.ai/download."
fi
if [[ "$(pmset -g | awk '$1 == "sleep" {print $2}')" == "0" ]]; then
  ok "Mac'en går ikke i dvale"
else
  adv "Mac'en kan gå i dvale. Se docs/MAC.md, trin 5."
fi

print -P "\n%BFærdigt.%b Næste skridt (docs/MAC.md):"
print "   - garmin-mcp login --person <navn>    for hver person med Garmin-ur"
print "   - ugeplan-mcp telegram-opsaet         (og evt. ugeplan-mcp login nemlig / bilka)"
print "   - genstart Claude helt (Cmd+Q), og kør tjekket:  zsh ${0:a:h}/tjek.zsh"
print "   Åbn en ny Terminal, hvis kommandoerne ikke findes (uv lægger $BIN i PATH)."
