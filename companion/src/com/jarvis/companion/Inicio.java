package com.jarvis.companion;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.provider.Settings;
import android.view.Gravity;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONObject;

/** Pantalla de estado: permiso de accesibilidad, conexión con el PC y últimos eventos. */
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
        Button probar = new Button(this);
        probar.setText("Probar conexión con el PC");
        probar.setOnClickListener(v -> {
            estado.setText("Probando…");
            new Thread(() -> {
                Object[] r = Conexion.post(this, "/app/hola", new JSONObject(), 8000);
                int codigo = (int) r[0];
                Conexion.anotar(this, codigo == 200 ? "ultimo_contacto" : "ultimo_error",
                        codigo == 200 ? "prueba OK con el PC" : "prueba fallida: " + (codigo == -1 ? r[1] : "el PC respondió " + codigo));
                runOnUiThread(this::pintar);
            }).start();
        });
        l.addView(titulo);
        l.addView(estado);
        l.addView(activar);
        l.addView(probar);
        setContentView(l);
    }

    @Override
    protected void onResume() {
        super.onResume();
        pintar();
    }

    private void pintar() {
        String activos = Settings.Secure.getString(getContentResolver(), Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
        boolean permiso = activos != null && activos.contains(getPackageName());
        estado.setText(
            "Versión " + Conexion.VERSION + "\n\n" +
            "Permiso de accesibilidad: " + (permiso ? "✅ activado" : "❌ desactivado (actívalo abajo)") + "\n" +
            "Conexión con el PC: " + Conexion.prefs(this).getString("ultimo_contacto", "todavía no") + "\n" +
            "Último envío: " + Conexion.prefs(this).getString("ultimo_envio", "ninguno") + "\n" +
            "Último error: " + Conexion.prefs(this).getString("ultimo_error", "ninguno") + "\n\n" +
            "Esta app solo pulsa «Enviar» en WhatsApp para los mensajes que tú confirmas a JARVIS.");
    }
}
