package com.jarvis.companion;

import android.accessibilityservice.AccessibilityService;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import org.json.JSONObject;

import java.net.URLEncoder;
import java.util.List;

/**
 * El corazón de la app. Mientras el permiso de accesibilidad está activado:
 *  1. Mantiene la conexión con JARVIS en el PC (pregunta en bucle si hay trabajo).
 *  2. Cuando llega un WhatsApp YA confirmado por el dueño, abre el chat con el texto escrito,
 *     pulsa "Enviar" solo si el texto escrito es exactamente el de la orden, y comprueba que se envió.
 *  3. Informa al PC del resultado y de cualquier error.
 * No lee ni guarda los chats.
 */
public class Accesibilidad extends AccessibilityService {
    static volatile boolean activa = false;
    private static final String[] CAMPOS = {"com.whatsapp:id/entry", "com.whatsapp.w4b:id/entry"};
    private static final String[] ENVIAR = {"com.whatsapp:id/send", "com.whatsapp.w4b:id/send"};

    private final Handler principal = new Handler(Looper.getMainLooper());
    private volatile boolean funcionando = false;
    // Trabajo en curso (un solo WhatsApp cada vez)
    private volatile long trabajoId = -1;
    private volatile String textoEsperado = null;
    private volatile long caduca = 0;
    private volatile boolean pulsado = false;

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        activa = true;
        funcionando = true;
        new Thread(this::bucle, "jarvis-conexion").start();
    }

    @Override
    public void onDestroy() {
        funcionando = false;
        activa = false;
        super.onDestroy();
    }

    /** Pregunta al PC si hay trabajo. La petición se queda abierta hasta 25 s (casi no gasta batería). */
    private void bucle() {
        int fallos = 0;
        while (funcionando) {
            Object[] r = Conexion.post(this, "/app/espera", new JSONObject(), 35_000);
            int codigo = (int) r[0];
            if (codigo == 200) {
                fallos = 0;
                Conexion.anotar(this, "ultimo_contacto", "conectada con el PC");
                try {
                    JSONObject t = new JSONObject((String) r[1]);
                    if ("whatsapp".equals(t.getString("tipo"))) {
                        JSONObject d = t.getJSONObject("datos");
                        long id = t.getLong("id");
                        principal.post(() -> empezarWhatsapp(id, d.optString("numero"), d.optString("texto")));
                    }
                } catch (Exception e) {
                    Conexion.error(this, "trabajo ilegible: " + e.getMessage());
                }
            } else if (codigo == 204) {
                fallos = 0;
                Conexion.anotar(this, "ultimo_contacto", "conectada con el PC");
            } else {
                fallos++;
                String motivo = codigo == -1 ? (String) r[1] : "el PC respondió " + codigo;
                Conexion.anotar(this, "ultimo_error", "sin conexión con el PC: " + motivo);
                if (fallos == 3 && codigo != -1) Conexion.error(this, "sin conexión con el PC: " + motivo);
                dormir(Math.min(30_000, 2_000L * fallos));
            }
        }
    }

    private void empezarWhatsapp(long id, String numero, String texto) {
        if (texto == null || texto.isEmpty() || numero == null || numero.isEmpty()) {
            terminar(id, "error", "orden sin número o sin texto");
            return;
        }
        trabajoId = id;
        textoEsperado = texto;
        caduca = System.currentTimeMillis() + 30_000;
        pulsado = false;
        try {
            String url = "https://wa.me/" + numero.replace("+", "") + "?text=" + URLEncoder.encode(texto, "UTF-8").replace("+", "%20");
            Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
            // WhatsApp normal y, si no, WhatsApp Business. Se intenta abrir de verdad (no basta con "verlo").
            String paquete = instalado("com.whatsapp.w4b") && !instalado("com.whatsapp") ? "com.whatsapp.w4b" : "com.whatsapp";
            i.setPackage(paquete);
            try {
                startActivity(i);
            } catch (android.content.ActivityNotFoundException sinApp) {
                i.setPackage(paquete.equals("com.whatsapp") ? "com.whatsapp.w4b" : "com.whatsapp");
                try {
                    startActivity(i);
                } catch (android.content.ActivityNotFoundException tampoco) {
                    terminar(id, "error", "WhatsApp no está instalado (no se pudo abrir ni WhatsApp ni WhatsApp Business)");
                    return;
                }
            }
        } catch (Exception e) {
            terminar(id, "error", "no pude abrir WhatsApp: " + e.getMessage());
            return;
        }
        // Si en 30 s no se ha podido pulsar Enviar, se dice el motivo (nunca se da por enviado)
        principal.postDelayed(() -> {
            if (trabajoId == id && !pulsado) terminar(id, "error", diagnostico());
        }, 30_000);
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent e) {
        if (textoEsperado == null || pulsado || System.currentTimeMillis() > caduca) return;
        AccessibilityNodeInfo raiz = getRootInActiveWindow();
        if (raiz == null) return;
        AccessibilityNodeInfo campo = buscar(raiz, CAMPOS);
        if (campo == null || campo.getText() == null) return;
        if (!normalizar(campo.getText().toString()).equals(normalizar(textoEsperado))) return;
        AccessibilityNodeInfo boton = buscar(raiz, ENVIAR);
        if (boton == null) return;
        pulsado = true;
        final long id = trabajoId;
        if (!boton.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
            terminar(id, "error", "WhatsApp no dejó pulsar Enviar");
            return;
        }
        // Comprobación: tras pulsar, la caja de texto tiene que quedarse vacía
        principal.postDelayed(() -> {
            AccessibilityNodeInfo r2 = getRootInActiveWindow();
            AccessibilityNodeInfo c2 = r2 == null ? null : buscar(r2, CAMPOS);
            String queda = (c2 == null || c2.getText() == null) ? "" : normalizar(c2.getText().toString());
            if (queda.equals(normalizar(textoEsperado == null ? "" : textoEsperado))) {
                terminar(id, "error", "pulsé Enviar pero el mensaje sigue escrito");
            } else {
                terminar(id, "enviado", "WhatsApp enviado");
            }
        }, 1500);
    }

    private String diagnostico() {
        AccessibilityNodeInfo raiz = getRootInActiveWindow();
        if (raiz == null) return "no se abrió WhatsApp (o no puedo ver la pantalla)";
        String paquete = String.valueOf(raiz.getPackageName());
        if (!paquete.startsWith("com.whatsapp")) return "WhatsApp no llegó a abrirse (pantalla actual: " + paquete + ")";
        AccessibilityNodeInfo campo = buscar(raiz, CAMPOS);
        if (campo == null) return "WhatsApp se abrió pero no encontré la caja de texto del chat";
        return "el texto escrito en el chat no coincide con el confirmado, así que no lo envié";
    }

    private void terminar(long id, String estado, String detalle) {
        if (trabajoId == id) {
            textoEsperado = null;
            trabajoId = -1;
        }
        Conexion.anotar(this, "ultimo_envio", estado + ": " + detalle);
        new Thread(() -> {
            try {
                Conexion.post(this, "/app/resultado",
                        new JSONObject().put("id", id).put("estado", estado).put("detalle", detalle), 10_000);
            } catch (Exception ignored) {
            }
        }).start();
    }

    private boolean instalado(String paquete) {
        try {
            getPackageManager().getPackageInfo(paquete, 0);
            return true;
        } catch (PackageManager.NameNotFoundException e) {
            return false;
        }
    }

    private static AccessibilityNodeInfo buscar(AccessibilityNodeInfo raiz, String[] ids) {
        for (String id : ids) {
            List<AccessibilityNodeInfo> nodos = raiz.findAccessibilityNodeInfosByViewId(id);
            if (nodos != null && !nodos.isEmpty()) return nodos.get(0);
        }
        return null;
    }

    private static String normalizar(String s) {
        return s.replace(' ', ' ').trim();
    }

    private static void dormir(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException ignored) {
        }
    }

    @Override
    public void onInterrupt() {}
}
