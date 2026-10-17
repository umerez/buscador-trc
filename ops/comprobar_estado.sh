#!/bin/zsh
# Comprueba que la pasada nocturna del buscador está viva en ESTE Mac. Sale con código 1 si algo falla.
# Uso: ops/comprobar_estado.sh
set -u
DIR="$(cd "$(dirname "$0")/.." && pwd)"
LABEL=com.umerez.buscador-trc
DOMINIO="gui/$(id -u)"
PROBLEMAS=0
mal() { echo "  [MAL] $1"; PROBLEMAS=$((PROBLEMAS+1)); }
bien() { echo "  [OK]  $1"; }

echo "== launchd"
if [ -f "$HOME/Library/LaunchAgents/$LABEL.plist" ]; then bien "plist instalado"; else mal "plist no instalado (ejecuta ops/instalar_launchd.sh)"; fi
if launchctl print "$DOMINIO/$LABEL" >/dev/null 2>&1; then
  bien "agente cargado en launchd"
  launchctl print "$DOMINIO/$LABEL" | grep -E 'state =|runs =|last exit code' | sed 's/^/        /'
else
  mal "agente NO cargado en launchd (ejecuta ops/instalar_launchd.sh)"
fi

echo "== última pasada"
if [ -f "$DIR/logs/ultimo_estado.txt" ]; then
  cat "$DIR/logs/ultimo_estado.txt" | sed 's/^/        /'
  grep -q 'rc=0' "$DIR/logs/ultimo_estado.txt" && bien "terminó sin error" || mal "la última pasada terminó con error"
  EDAD=$(( $(date +%s) - $(stat -f %m "$DIR/logs/ultimo_estado.txt") ))
  [ "$EDAD" -lt 93600 ] && bien "hace menos de 26 h" || mal "la última pasada tiene más de 26 h ($((EDAD/3600)) h): no ha corrido esta noche"
else
  mal "no hay logs/ultimo_estado.txt: la pasada nocturna nunca ha corrido con este script"
fi

echo "== GitHub"
cd "$DIR" || exit 1
git log -1 --format='        último commit: %h %ad %s' --date=format:'%Y-%m-%d %H:%M'
gh auth token --user umerez >/dev/null 2>&1 && bien "gh tiene token de la cuenta umerez" || mal "gh no tiene token de la cuenta umerez (gh auth login)"

echo "== avisos del índice (estado.json)"
/usr/bin/python3 - <<'PY' 2>/dev/null || echo "        (no se pudo leer estado.json)"
import json
e = json.load(open("docs/data/estado.json", encoding="utf-8"))
hay = False
for t, r in e.items():
    if not r.get("ok", True) or r.get("avisos"):
        hay = True
        print(f"        {t}: ok={r.get('ok')} avisos={r.get('avisos', 0)} error={r.get('error')}")
        for a in r.get("avisos_detalle", []):
            print("           -", a)
if not hay:
    print("        sin avisos")
PY

echo
[ "$PROBLEMAS" -eq 0 ] && echo "Todo en orden." || echo "$PROBLEMAS problema(s)."
exit $(( PROBLEMAS > 0 ))
