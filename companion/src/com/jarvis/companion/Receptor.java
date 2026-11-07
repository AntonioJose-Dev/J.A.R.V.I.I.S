package com.jarvis.companion;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Recibe las órdenes del agente de JARVIS (Termux): configurar el secreto (una vez) y enviar un WhatsApp. */
public class Receptor extends BroadcastReceiver {
    @Override
    public void onReceive(Context c, Intent i) {
        String accion = i.getAction();
        if ("com.jarvis.companion.CONFIGURAR".equals(accion)) {
            boolean ok = Orden.configurar(c, i.getStringExtra("secreto"));
            Orden.registrar(c, ok ? "configurada" : "configuracion rechazada");
            if (ok) Aviso.enviar(c, "configurada", 0);
            setResultCode(ok ? 1 : 0);
        } else if ("com.jarvis.companion.ESTADO".equals(accion)) {
            // Solo devuelve el último evento (p. ej. "enviado 1731000000000"); no cambia nada ni expone textos
            setResultCode(Orden.configurada(c) ? 1 : 2);
            String ultimo = Orden.prefs(c).getString("ultimo", "");
            setResultData(ultimo.contains(" ") ? ultimo.substring(ultimo.indexOf(' ') + 1) : ultimo);
        } else if ("com.jarvis.companion.ENVIAR".equals(accion)) {
            long marca;
            try {
                marca = Long.parseLong(i.getStringExtra("marca"));
            } catch (Exception e) {
                marca = 0;
            }
            boolean ok = Orden.recibir(c, i.getStringExtra("texto"), marca, i.getStringExtra("firma"));
            Orden.registrar(c, ok ? "orden aceptada" : "orden rechazada");
            setResultCode(ok ? 1 : 0);
        }
    }
}
