#!/data/data/com.termux/files/usr/bin/bash
# Instalador del agente de JARVIS en el móvil (ejecutar dentro de Termux):
#   curl -fsSL https://raw.githubusercontent.com/AntonioJose-Dev/J.A.R.V.I.I.S/main/movil/instalar.sh | bash
set -e
REPO="https://raw.githubusercontent.com/AntonioJose-Dev/J.A.R.V.I.I.S/main/movil"

echo "== Instalando Python y Termux:API =="
pkg update -y >/dev/null 2>&1 || true
pkg install -y python termux-api curl >/dev/null

echo "== Descargando el agente de JARVIS =="
mkdir -p ~/jarvis ~/.termux/boot
curl -fsSL "$REPO/agente.py" -o ~/jarvis/agente.py

if [ ! -s ~/.jarvis_token ]; then
  echo
  echo "Escribe el código secreto que te ha dado el PC (scripts/configurar_movil.py):"
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

echo "== Arrancando el agente =="
pkill -f "jarvis/agente.py" 2>/dev/null || true
pkill -f ".termux/boot/jarvis.sh" 2>/dev/null || true
nohup ~/.termux/boot/jarvis.sh >/dev/null 2>&1 &
sleep 2
echo
echo "Listo. Ahora dile al PC el nombre de este móvil en Tailscale (sale en la app de Tailscale)."
echo "Si Android pide permisos a Termux:API (ubicación, SMS, notificaciones...), acéptalos."
