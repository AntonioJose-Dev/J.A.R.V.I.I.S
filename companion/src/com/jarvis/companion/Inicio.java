package com.jarvis.companion;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.provider.Settings;
import android.view.Gravity;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Pantalla mínima: estado y un botón para activar el permiso de accesibilidad. */
public class Inicio extends Activity {
    private TextView estado;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.VERTICAL);
        l.setGravity(Gravity.CENTER);
        l.setPadding(48, 48, 48, 48);
        TextView titulo = new TextView(this);
        titulo.setText("J.A.R.V.I.S.");
        titulo.setTextSize(28);
        titulo.setGravity(Gravity.CENTER);
        estado = new TextView(this);
        estado.setTextSize(16);
        estado.setPadding(0, 32, 0, 32);
        Button activar = new Button(this);
        activar.setText("Activar permiso de accesibilidad");
        activar.setOnClickListener(v -> startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)));
        Button reconectar = new Button(this);
        reconectar.setText("Reconectar con JARVIS");
        reconectar.setOnClickListener(v -> {
            estado.setText("Conectando con JARVIS…");
            new Thread(() -> {
                String r = Agente.emparejar(this);
                Orden.registrar(this, "ok".equals(r) ? "conectada con JARVIS" : "no se pudo conectar: " + r);
                runOnUiThread(this::onResume);
            }).start();
        });
        l.addView(titulo);
        l.addView(estado);
        l.addView(activar);
        l.addView(reconectar);
        setContentView(l);
    }

    @Override
    protected void onResume() {
        super.onResume();
        String activos = Settings.Secure.getString(getContentResolver(), Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
        boolean permiso = activos != null && activos.contains(getPackageName());
        String ultimo = Orden.prefs(this).getString("ultimo", "nada todavía");
        estado.setText(
            "Permiso de accesibilidad: " + (permiso ? "✅ activado" : "❌ desactivado") + "\n" +
            "Conectada con JARVIS: " + (Orden.configurada(this) ? "✅ sí" : "❌ todavía no") + "\n\n" +
            "Último evento: " + ultimo + "\n\n" +
            "Esta app solo pulsa «Enviar» en WhatsApp para los mensajes que tú confirmas a JARVIS.");
    }
}
