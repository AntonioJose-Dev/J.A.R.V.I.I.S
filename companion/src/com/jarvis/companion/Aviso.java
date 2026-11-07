package com.jarvis.companion;

import android.content.Context;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * Avisa al agente de JARVIS (en este mismo móvil, 127.0.0.1) de lo que ha pasado: "configurada",
 * "enviado", "fallo_pulsar". El aviso va firmado con el secreto compartido, así el agente sabe que es
 * de verdad de esta app. No sale del teléfono.
 */
final class Aviso {
    private Aviso() {}

    static void enviar(Context c, String evento, long marca) {
        final String secreto = Orden.prefs(c).getString("secreto", null);
        if (secreto == null) return;
        new Thread(() -> {
            try {
                String firma = Orden.hmac(secreto, evento + "\n" + marca);
                String json = "{\"evento\":\"" + evento + "\",\"marca\":\"" + marca + "\",\"firma\":\"" + firma + "\"}";
                HttpURLConnection con = (HttpURLConnection) new URL("http://127.0.0.1:8765/companion").openConnection();
                con.setRequestMethod("POST");
                con.setConnectTimeout(3000);
                con.setReadTimeout(3000);
                con.setDoOutput(true);
                con.setRequestProperty("Content-Type", "application/json");
                try (OutputStream os = con.getOutputStream()) {
                    os.write(json.getBytes(StandardCharsets.UTF_8));
                }
                con.getResponseCode();
                con.disconnect();
            } catch (Exception ignored) {
                // Si el agente no está en marcha, no pasa nada: JARVIS dirá que no pudo comprobarlo
            }
        }).start();
    }
}
