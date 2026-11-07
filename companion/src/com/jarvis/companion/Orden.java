package com.jarvis.companion;

import android.content.Context;
import android.content.SharedPreferences;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/**
 * La orden pendiente de enviar un WhatsApp, y su verificación.
 *
 * Una orden solo es válida si:
 *  - lleva la firma HMAC-SHA256(secreto, marca_de_tiempo + "\n" + texto) correcta,
 *  - tiene menos de 60 segundos,
 *  - y no se ha usado ya (cada orden sirve para un solo envío).
 */
final class Orden {
    static final long VALIDEZ_MS = 60_000;
    private static final String PREFS = "jarvis";

    private static String texto;
    private static long caduca;

    private Orden() {}

    static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    static boolean configurada(Context c) {
        return prefs(c).getString("secreto", null) != null;
    }

    /** El secreto se fija una sola vez (desde el agente de JARVIS). Para cambiarlo, borrar datos de la app. */
    static synchronized boolean configurar(Context c, String secreto) {
        if (secreto == null || secreto.length() < 32 || configurada(c)) return false;
        prefs(c).edit().putString("secreto", secreto).apply();
        return true;
    }

    static synchronized boolean recibir(Context c, String nuevoTexto, long marca, String firma) {
        String secreto = prefs(c).getString("secreto", null);
        long ahora = System.currentTimeMillis();
        if (secreto == null || nuevoTexto == null || firma == null) return false;
        if (Math.abs(ahora - marca) > VALIDEZ_MS) return false;
        if (prefs(c).getLong("ultima_marca", 0) >= marca) return false;  // no se puede reutilizar una orden
        String esperada = hmac(secreto, marca + "\n" + nuevoTexto);
        if (!MessageDigest.isEqual(esperada.getBytes(StandardCharsets.UTF_8), firma.getBytes(StandardCharsets.UTF_8))) {
            return false;
        }
        prefs(c).edit().putLong("ultima_marca", marca).apply();
        texto = nuevoTexto;
        caduca = ahora + VALIDEZ_MS;
        return true;
    }

    /** Devuelve el texto pendiente (si sigue vigente) y lo consume si `consumir`. */
    static synchronized String pendiente(boolean consumir) {
        if (texto == null || System.currentTimeMillis() > caduca) {
            texto = null;
            return null;
        }
        String t = texto;
        if (consumir) texto = null;
        return t;
    }

    static void registrar(Context c, String evento) {
        prefs(c).edit().putString("ultimo", System.currentTimeMillis() + " " + evento).apply();
    }

    static String hmac(String secreto, String datos) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secreto.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            byte[] r = mac.doFinal(datos.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder();
            for (byte b : r) sb.append(String.format("%02x", b));
            return sb.toString();
        } catch (Exception e) {
            return "";
        }
    }
}
