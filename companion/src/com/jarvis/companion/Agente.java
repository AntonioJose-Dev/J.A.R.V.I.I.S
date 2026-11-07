package com.jarvis.companion;

import android.content.Context;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** Habla con el agente de JARVIS que corre en este mismo móvil (Termux, 127.0.0.1:8765). Nada sale del teléfono. */
final class Agente {
    private static final String BASE = "http://127.0.0.1:8765/companion";

    private Agente() {}

    /** Respuesta: código HTTP y cuerpo (JSON o vacío). Nunca se llama desde el hilo principal. */
    static Object[] post(String ruta, String json) {
        try {
            HttpURLConnection con = (HttpURLConnection) new URL(BASE + ruta).openConnection();
            con.setRequestMethod("POST");
            con.setConnectTimeout(3000);
            con.setReadTimeout(5000);
            con.setDoOutput(true);
            con.setRequestProperty("Content-Type", "application/json");
            try (OutputStream os = con.getOutputStream()) {
                os.write(json.getBytes(StandardCharsets.UTF_8));
            }
            int codigo = con.getResponseCode();
            String cuerpo = "";
            InputStream in = codigo < 400 ? con.getInputStream() : con.getErrorStream();
            if (in != null) {
                ByteArrayOutputStream b = new ByteArrayOutputStream();
                byte[] buf = new byte[4096];
                int n;
                while ((n = in.read(buf)) > 0) b.write(buf, 0, n);
                cuerpo = b.toString("UTF-8");
            }
            con.disconnect();
            return new Object[]{codigo, cuerpo};
        } catch (Exception e) {
            return new Object[]{-1, String.valueOf(e.getMessage())};
        }
    }

    /** Pide el secreto al agente (solo funciona si el agente aún no tiene ninguna app emparejada). */
    static String emparejar(Context c) {
        Object[] r = post("/emparejar", "{}");
        int codigo = (int) r[0];
        if (codigo == 200) {
            try {
                String secreto = new JSONObject((String) r[1]).getString("secreto");
                Orden.olvidar(c);
                if (!Orden.configurar(c, secreto)) return "secreto no válido";
                Aviso.enviar(c, "configurada", 0);
                return "ok";
            } catch (Exception e) {
                return "respuesta rara del agente";
            }
        }
        if (codigo == 409) return "JARVIS ya tiene otra app emparejada: pídele que la olvide y vuelve a pulsar";
        if (codigo == -1) return "no encuentro el agente de JARVIS (¿está Termux en marcha?)";
        return "el agente dijo " + codigo;
    }

    /** Pregunta si hay un WhatsApp confirmado esperando. Si lo hay y la firma es buena, queda pendiente. */
    static boolean pedirOrden(Context c) {
        String secreto = Orden.prefs(c).getString("secreto", null);
        if (secreto == null) return false;
        long ts = System.currentTimeMillis();
        String firma = Orden.hmac(secreto, "orden\n" + ts);
        Object[] r = post("/orden", "{\"ts\":\"" + ts + "\",\"firma\":\"" + firma + "\"}");
        if ((int) r[0] != 200) return false;
        try {
            JSONObject o = new JSONObject((String) r[1]);
            return Orden.recibir(c, o.getString("texto"), Long.parseLong(o.getString("marca")), o.getString("firma"));
        } catch (Exception e) {
            return false;
        }
    }
}
