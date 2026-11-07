#!/data/data/com.termux/files/usr/bin/bash
# Instalador del agente de JARVIS en el móvil (ejecutar dentro de Termux):
#   curl -fsSL https://raw.githubusercontent.com/AntonioJose-Dev/J.A.R.V.I.I.S/main/movil/instalar.sh | JARVIS_TOKEN=... bash
REPO="https://raw.githubusercontent.com/AntonioJose-Dev/J.A.R.V.I.I.S/main/movil"
export DEBIAN_FRONTEND=noninteractive
OPCIONES=(-y -o Dpkg::Options::=--force-confnew -o Dpkg::Options::=--force-confdef)

reintentar() {  # reintentar <descripción> <comando...>
  local desc="$1"; shift
  for intento in 1 2 3; do
    if "$@"; then return 0; fi
    echo "   (falló '$desc', reintento $intento/3…)"
    dpkg --configure -a >/dev/null 2>&1 || true
    sleep 3
  done
  echo "❌ No se pudo: $desc. Mándale una captura de esta pantalla a Claude."
  exit 1
}

echo "== 1/4 Preparando Termux (la primera vez tarda unos minutos) =="
dpkg --configure -a >/dev/null 2>&1 || true
reintentar "actualizar la lista de paquetes" bash -c "yes | pkg update ${OPCIONES[*]}"
reintentar "actualizar Termux" apt-get "${OPCIONES[@]}" upgrade

echo "== 2/4 Instalando Python y Termux:API =="
reintentar "instalar Python y Termux:API" apt-get "${OPCIONES[@]}" install python termux-api curl

echo "== 3/4 Descargando el agente de JARVIS =="
mkdir -p ~/jarvis ~/.termux/boot
reintentar "descargar el agente" curl -fsSL "$REPO/agente.py" -o ~/jarvis/agente.py

if [ -n "$JARVIS_TOKEN" ]; then
  printf '%s' "$JARVIS_TOKEN" | tr -d ' -' > ~/.jarvis_token
  chmod 600 ~/.jarvis_token
elif [ ! -s ~/.jarvis_token ]; then
  echo
  echo "Escribe el código secreto que te ha dado el PC:"
  read -r TOKEN < /dev/tty
  printf '%s' "$TOKEN" | tr -d ' -' > ~/.jarvis_token
  chmod 600 ~/.jarvis_token
fi

cat > ~/.termux/boot/jarvis.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
cd ~/jarvis
while true; do
  python agente.py >> ~/jarvis/agente.log 2>&1
  sleep 5
done
EOF
chmod +x ~/.termux/boot/jarvis.sh

echo "== 4/4 Arrancando el agente =="
pkill -f "jarvis/agente.py" 2>/dev/null || true
pkill -f ".termux/boot/jarvis.sh" 2>/dev/null || true
pkill -f "python agente.py" 2>/dev/null || true
nohup ~/.termux/boot/jarvis.sh >/dev/null 2>&1 &
sleep 3
if pgrep -f "python agente.py" >/dev/null; then
  echo
  echo "✅ Listo. El agente de JARVIS está en marcha."
  echo "Si Android pide permisos a Termux:API (ubicación, SMS, notificaciones...), acéptalos."
else
  echo "❌ El agente no arrancó. Mira ~/jarvis/agente.log o mándale captura a Claude:"
  tail -n 5 ~/jarvis/agente.log 2>/dev/null
fi
