#!/bin/zsh
# Tjekliste for Mac'en, der altid er tændt (docs/MAC.md). Ændrer intet. Kør:
#   zsh ~/ugeplan-mac/tjek.zsh
# Viser kun niveauer (rolig/normal/hård), aldrig tal fra uret.

export PATH="$HOME/.local/bin:$PATH"
DATA="${HANDLE_MCP_DATA:-$HOME/.local/share/handle-mcp}"
BIN="$(uv tool dir --bin 2>/dev/null || print "$HOME/.local/bin")"
PY="$(uv tool dir 2>/dev/null)/ugeplan-mcp/bin/python"
FEJL=0

gron() { print "  [OK]   $1"; }
rod()  { print "  [FEJL] $1"; FEJL=$((FEJL + 1)); }
gul()  { print "  [?]    $1"; }

# Som Claude-appen ser verden: tomt miljø og kort PATH.
som_appen() { env -i HOME="$HOME" USER="$USER" LANG=da_DK.UTF-8 PATH=/usr/bin:/bin:/usr/sbin:/sbin "$@"; }

print "\nMaskinen"
[[ "$(pmset -g | awk '$1 == "sleep" {print $2}')" == "0" ]] && gron "går ikke i dvale" || rod "kan gå i dvale (MAC.md trin 5)"
osascript -e 'tell application "System Events" to get the name of every login item' 2>/dev/null | grep -q Claude \
  && gron "Claude starter ved login" || rod "Claude starter ikke ved login (MAC.md trin 4)"
pgrep -xq Claude && gron "Claude kører" || rod "Claude kører ikke"
pgrep -f "handle_mcp.server telegram" >/dev/null && gron "Telegram-lytteren kører" || rod "Telegram-lytteren kører ikke (åbn Claude, eller se $DATA/telegram-lytter.log)"
[[ -d /Applications/Tailscale.app ]] && gron "Tailscale er installeret" || gul "Tailscale er ikke installeret (MAC.md trin 6)"

print "\nInstallation"
[[ -x "$BIN/ugeplan-mcp" && -x "$BIN/garmin-mcp" && -x "$PY" ]] && gron "ugeplan-mcp og garmin-mcp i $BIN" || rod "ugeplan-mcp[garmin] er ikke installeret (kør installer.zsh)"
grep -q "\"$BIN/ugeplan-mcp\"" "$HOME/Library/Application Support/Claude/claude_desktop_config.json" 2>/dev/null \
  && gron "Claude starter ugeplan-mcp herfra" || rod "Claude-konfigurationen peger ikke på $BIN/ugeplan-mcp (kør installer.zsh)"

print "\nGarmin (belastning --alle, som appen kører den)"
UD="$(mktemp)"; ERR="$(mktemp)"
som_appen "$BIN/garmin-mcp" belastning --alle --dato "$(date +%F)" > "$UD" 2> "$ERR"
"$PY" - "$UD" "$ERR" <<'PY' || FEJL=$((FEJL + 1))
import json, sys
try:
    personer = json.load(open(sys.argv[1], encoding="utf-8")).get("personer") or {}
except ValueError:
    sidst = (open(sys.argv[2], encoding="utf-8", errors="replace").read().strip().splitlines() or [""])[-1]
    print(f"  [FEJL] intet svar: {sidst[:200]}"); sys.exit(1)
if not personer:
    print("  [FEJL] ingen er logget ind (garmin-mcp login --person NAVN)"); sys.exit(1)
fejl = 0
for navn, d in personer.items():
    if "fejl" in d:
        print(f"  [FEJL] {navn}: {d['fejl']}"); fejl += 1
    else:
        print(f"  [OK]   {navn}: {d.get('niveau')}{' (foreløbig)' if d.get('foreloebig') else ''}")
sys.exit(1 if fejl else 0)
PY
rm -f "$UD" "$ERR"

print "\nugeplan-mcp (det lytteren ser)"
som_appen "$PY" - <<'PY' || FEJL=$((FEJL + 1))
import time
from datetime import date
from handle_mcp import profil, traening
from handle_mcp.lokal import laes, mappe

fejl = 0
def ok(t): print(f"  [OK]   {t}")
def nej(t):
    global fejl; fejl += 1; print(f"  [FEJL] {t}")

print(f"  data: {mappe()}")
p = profil.hent()
ok(f"aftensmad kl. {p.aftensmad}") if p.aftensmad else nej("aftensmad er ikke sat i profilen")
if p.garmin:
    ok("Garmin-ja i profilen: " + ", ".join(x["navn"] for x in p.garmin))
else:
    nej('ingen har sagt ja til Garmin i profilen (sig fx "Anna må bruge sine Garmin-data")')
if traening.konfiguration():
    nej("garmin-kommando.json fra en ældre opsætning bruges i stedet for Garmin-delen (kør installer.zsh)")
elif traening.garmin_installeret():
    ok("lytteren henter niveauet direkte fra Garmin-delen")
else:
    nej("Garmin-delen mangler i miljøet (kør installer.zsh)")
if p.garmin:
    for navn, d in traening.hent_niveauer(date.today()).items():
        (ok if d.get("niveau") != "ukendt" else nej)(f"lytteren får {navn}: {d.get('niveau')}")
sidste = float(laes("traening").get("sidste_tjek") or 0)
if sidste:
    minutter = (time.time() - sidste) / 60
    t = time.strftime("%d/%m %H:%M", time.localtime(sidste))
    if 6 <= time.localtime().tm_hour < 21 and minutter > 35:
        nej(f"sidste træningstjek {t}, {minutter:.0f} min siden (skal være hver 30. min kl. 6-21)")
    else:
        ok(f"sidste træningstjek {t}")
else:
    nej("lytteren har ikke tjekket træning endnu")
idag = date.today().isoformat()
for h in [h for h in traening.haendelser() if str(h.get("tid", "")).startswith(idag)]:
    ok(f"i dag {h['tid'][11:16]}: {h['type']} ({h.get('status', 'sendt')})")
raise SystemExit(1 if fejl else 0)
PY

print "\nSidste linjer i lytterens log"
if [[ -f "$DATA/telegram-lytter.log" ]]; then
  tail -n 5 "$DATA/telegram-lytter.log" | sed 's/^/  /'
else
  gul "ingen log endnu"
fi

print ""
(( FEJL == 0 )) && print "Alt grønt." || print "$FEJL ting skal ordnes."
exit $(( FEJL > 0 ))
