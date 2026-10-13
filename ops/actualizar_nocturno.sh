#!/bin/zsh
# Pasada nocturna del índice: recorre el año en curso en los diez tribunales, hace commit y sube a GitHub.
# La lanza launchd (ops/com.umerez.buscador-trc.plist) a las 03:30. Log en logs/nocturno.log.
set -u
cd "$(dirname "$0")/.." || exit 1
PY=/Library/Frameworks/Python.framework/Versions/3.9/bin/python3
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
LOG=logs/nocturno.log
# El push va siempre con la cuenta umerez, sea cual sea la activa en gh (la de Clara es EstebanIpar,
# que no puede escribir aquí). Se vacía el ayudante global y se pone uno que pide a gh el token de umerez.
CRED='!f(){ echo username=umerez; echo "password=$(gh auth token --user umerez)"; }; f'
{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S')"
  git pull --rebase --autostash -q origin main || { echo "git pull falló"; exit 1; }
  "$PY" construir_indice.py --actual
  git add docs/data
  if git diff --cached --quiet; then
    echo "Sin cambios en el índice"
  else
    git -c user.name=umerez -c user.email=esteban@umerez.eu commit -q -m "Índice actualizado $(date '+%Y-%m-%d')" \
      && { git -c credential.helper= -c credential.helper="$CRED" push -q origin main \
             && echo "Subido a GitHub" || echo "git push falló"; }
  fi
} >> "$LOG" 2>&1
# el log no crece sin límite: se conservan las últimas 5.000 líneas
tail -n 5000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
