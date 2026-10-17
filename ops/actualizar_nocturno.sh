#!/bin/zsh
# Pasada nocturna del índice: recorre el año en curso en los diez tribunales, hace commit y sube a GitHub.
# La lanza launchd (ops/com.umerez.buscador-trc.plist) a las 03:30 en Yoda (Mac Mini). Log en logs/nocturno.log;
# el resultado de la última pasada queda en logs/ultimo_estado.txt (lo lee ops/comprobar_estado.sh).
set -u
cd "$(dirname "$0")/.." || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export LANG=es_ES.UTF-8 PYTHONIOENCODING=utf-8
mkdir -p logs
LOG=logs/nocturno.log
ESTADO=logs/ultimo_estado.txt

# Una sola pasada a la vez (un lanzamiento a mano mientras corre la nocturna no debe pisarla).
LOCK=/tmp/com.umerez.buscador-trc.lock
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +240 2>/dev/null)" ]; then
    rmdir "$LOCK" 2>/dev/null; mkdir "$LOCK" || exit 1      # cerrojo obsoleto de una pasada que murió
  else
    echo "$(date '+%Y-%m-%d %H:%M:%S') ya hay una pasada en curso; se omite esta" >> "$LOG"
    exit 0
  fi
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

# Evita que el Mac se duerma por inactividad mientras dura la pasada.
/usr/bin/caffeinate -i -w $$ &

# Python con las dependencias (la 3.9 del instalador de python.org era la de R2-D2; en Yoda vale la primera que sirva).
PY=""
for c in /Library/Frameworks/Python.framework/Versions/3.9/bin/python3 "$PWD/.venv/bin/python" /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  if [ -x "$c" ] && "$c" -c 'import requests, bs4, lxml, cryptography' >/dev/null 2>&1; then PY="$c"; break; fi
done

# El push va siempre con la cuenta umerez, sea cual sea la activa en gh (la de Clara es EstebanIpar,
# que no puede escribir aquí). Se vacía el ayudante global y se pone uno que pide a gh el token de umerez.
CRED='!f(){ echo username=umerez; echo "password=$(gh auth token --user umerez)"; }; f'

pasada() {
  echo "===== $(date '+%Y-%m-%d %H:%M:%S')"
  [ -n "$PY" ] || { echo "ERROR: ningún Python con requests, bs4, lxml y cryptography"; return 2; }
  gh auth token --user umerez >/dev/null 2>&1 || echo "AVISO: gh no da token para la cuenta umerez; el push fallará"
  git pull --rebase --autostash -q origin main || { echo "ERROR: git pull falló"; return 3; }
  "$PY" construir_indice.py --actual || { echo "ERROR: construir_indice.py terminó con error"; return 4; }
  git add docs/data
  if git diff --cached --quiet; then
    echo "Sin cambios en el índice"
    return 0
  fi
  git -c user.name=umerez -c user.email=esteban@umerez.eu commit -q -m "Índice actualizado $(date '+%Y-%m-%d')" \
    || { echo "ERROR: git commit falló"; return 5; }
  git -c credential.helper= -c credential.helper="$CRED" push -q origin main \
    && echo "Subido a GitHub" || { echo "ERROR: git push falló"; return 6; }
}

SALIDA=$(mktemp)
pasada > "$SALIDA" 2>&1
RC=$?
cat "$SALIDA" >> "$LOG"
RESUMEN=$(grep -E '^(Índice:|Sin cambios|Subido|ERROR|AVISO)' "$SALIDA" | tr '\n' ' ')
echo "$(date '+%Y-%m-%dT%H:%M:%S%z') rc=$RC $RESUMEN" > "$ESTADO"
rm -f "$SALIDA"

# Si falló, aviso en el escritorio de Yoda (si no hay sesión gráfica, simplemente no sale).
if [ "$RC" -ne 0 ]; then
  /usr/bin/osascript -e "display notification \"La pasada nocturna del buscador falló (código $RC). Mira logs/nocturno.log\" with title \"Buscador TRC\"" >/dev/null 2>&1
fi

# el log no crece sin límite: se conservan las últimas 5.000 líneas
tail -n 5000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
exit "$RC"
