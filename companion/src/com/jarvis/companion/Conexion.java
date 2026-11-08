package com.jarvis.companion;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * Conexión directa con JARVIS en el PC, por Tailscale (cifrado por WireGuard).
 * La dirección del PC y el código secreto van dentro de la app (se ponen al compilarla).
 */
final class Conexion {
    static final String VERSION = "1.11";

    private Conexion() {}

    static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences("jarvis", Context.MODE_PRIVATE);
    }

    static void anotar(Context c, String clave, String valor) {
        prefs(c).edit().putString(clave, new java.text.SimpleDateFormat("HH:mm:ss").format(new java.util.Date())
                + " " + valor).apply();
    }

    /** POST al PC. Devuelve {código HTTP, cuerpo}. Código -1 = no se pudo conectar (el cuerpo lleva el motivo). */
    static Object[] post(Context c, String ruta, JSONObject datos, int esperaMs) {
        try {
            String base = c.getString(R.string.servidor_jarvis);
            HttpURLConnection con = (HttpURLConnection) new URL(base + ruta).openConnection();
            con.setRequestMethod("POST");
            con.setConnectTimeout(8000);
            con.setReadTimeout(esperaMs);
            con.setDoOutput(true);
            con.setRequestProperty("Content-Type", "application/json");
            con.setRequestProperty("X-Jarvis-Token", c.getString(R.string.token_jarvis));
            datos.put("version", VERSION);
            datos.put("accesibilidad", Accesibilidad.activa);
            try (OutputStream os = con.getOutputStream()) {
                os.write(datos.toString().getBytes(StandardCharsets.UTF_8));
            }
            int codigo = con.getResponseCode();
            String cuerpo = "";
            InputStream in = codigo < 400 ? con.getInputStream() : con.getErrorStream();
            if (in != null && codigo != 204) {
                ByteArrayOutputStream b = new ByteArrayOutputStream();
                byte[] buf = new byte[4096];
                int n;
                while ((n = in.read(buf)) > 0) b.write(buf, 0, n);
                cuerpo = b.toString("UTF-8");
            }
            con.disconnect();
            return new Object[]{codigo, cuerpo};
        } catch (Exception e) {
            return new Object[]{-1, e.getClass().getSimpleName() + ": " + e.getMessage()};
        }
    }

    /** Descarga un archivo del PC (p. ej. un audio). Lanza una excepción con el motivo si no se puede. */
    static byte[] descargar(Context c, String ruta, JSONObject datos, int esperaMs) throws Exception {
        HttpURLConnection con = (HttpURLConnection) new URL(c.getString(R.string.servidor_jarvis) + ruta).openConnection();
        con.setRequestMethod("POST");
        con.setConnectTimeout(8000);
        con.setReadTimeout(esperaMs);
        con.setDoOutput(true);
        con.setRequestProperty("Content-Type", "application/json");
        con.setRequestProperty("X-Jarvis-Token", c.getString(R.string.token_jarvis));
        datos.put("version", VERSION);
        datos.put("accesibilidad", Accesibilidad.activa);
        try (OutputStream os = con.getOutputStream()) {
            os.write(datos.toString().getBytes(StandardCharsets.UTF_8));
        }
        int codigo = con.getResponseCode();
        if (codigo != 200) {
            con.disconnect();
            throw new Exception("el PC respondió " + codigo);
        }
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        try (InputStream in = con.getInputStream()) {
            byte[] buf = new byte[16384];
            int n;
            while ((n = in.read(buf)) > 0) {
                b.write(buf, 0, n);
                if (b.size() > 5_000_000) throw new Exception("audio demasiado grande");
            }
        }
        con.disconnect();
        return b.toByteArray();
    }

    /** Avisa al PC de un error (así se puede ver sin capturas de pantalla). */
    static void error(Context c, String texto) {
        anotar(c, "ultimo_error", texto);
        try {
            post(c, "/app/hola", new JSONObject().put("error", texto), 8000);
        } catch (Exception ignored) {
        }
    }
}
