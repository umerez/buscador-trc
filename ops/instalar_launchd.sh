#!/bin/zsh
# Instala (o reinstala) en ESTE Mac el agente de launchd de la pasada nocturna y comprueba que queda cargado.
# Uso:  ops/instalar_launchd.sh            instala y comprueba
#       ops/instalar_launchd.sh --probar   además lanza una pasada ahora mismo (tarda unos 10-15 min)
set -u
DIR="$(cd "$(dirname "$0")/.." && pwd)"
LABEL=com.umerez.buscador-trc
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMINIO="gui/$(id -u)"

mkdir -p "$HOME/Library/LaunchAgents" "$DIR/logs"
chmod +x "$DIR"/ops/*.sh
# El plist del repositorio lleva la ruta de Yoda; si el repositorio está en otro sitio, se ajusta al instalar.
sed "s#/Users/umerez/Proyectos/buscador-trc#$DIR#g" "$DIR/ops/$LABEL.plist" > "$DEST" || exit 1
plutil -lint "$DEST" || exit 1

launchctl bootout "$DOMINIO/$LABEL" >/dev/null 2>&1
launchctl bootstrap "$DOMINIO" "$DEST" || { echo "No se pudo cargar el agente. ¿Hay sesión gráfica abierta en este Mac?"; exit 1; }
launchctl enable "$DOMINIO/$LABEL"

echo "--- estado en launchd"
launchctl print "$DOMINIO/$LABEL" | grep -E 'state =|path =|runs =|last exit code|Hour|Minute' || true
echo "--- plist instalado: $DEST"

if [ "${1:-}" = "--probar" ]; then
  echo "--- lanzando una pasada ahora (log en $DIR/logs/nocturno.log)"
  launchctl kickstart -k "$DOMINIO/$LABEL"
fi
echo "Listo. Comprobación posterior: ops/comprobar_estado.sh"
