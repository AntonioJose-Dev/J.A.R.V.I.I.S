package com.jarvis.companion;

import android.app.Activity;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInstaller;
import android.provider.Settings;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

import java.io.OutputStream;
import java.security.MessageDigest;

/**
 * «Actualizar JARVIS»: baja la última versión de la app desde TU PC (por Tailscale), comprueba que llega entera
 * (huella SHA-256) y abre el instalador de Android. Ya no hace falta pasar por Telegram.
 */
public class Actualizador extends BroadcastReceiver {

    /** ¿Hay una versión nueva en el PC? Cambia el texto del botón si la hay. */
    static void comprobar(Activity a, TextView boton) {
        new Thread(() -> {
            Object[] r = Conexion.post(a, "/app/version_apk", new JSONObject(), 8000);
            if ((int) r[0] != 200) return;
            try {
                String v = new JSONObject((String) r[1]).getString("version");
                if (!v.equals(Conexion.VERSION)) a.runOnUiThread(() -> boton.setText("⟳  ACTUALIZAR A LA " + v + " (NUEVA)"));
                else a.runOnUiThread(() -> boton.setText("⟳  JARVIS ESTÁ AL DÍA (" + v + ")"));
            } catch (Exception ignored) {
            }
        }).start();
    }

    static void empezar(Activity a, TextView boton) {
        if (!a.getPackageManager().canRequestPackageInstalls()) {
            Toast.makeText(a, "Permite a JARVIS instalar su actualización y vuelve a pulsar", Toast.LENGTH_LONG).show();
            a.startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    android.net.Uri.parse("package:" + a.getPackageName())));
            return;
        }
        if (Inicio.libreMb(a) < 300) {
            Toast.makeText(a, "Muy poco espacio libre (" + Inicio.libreMb(a) + " MB): libera al menos 1 GB e inténtalo otra vez",
                    Toast.LENGTH_LONG).show();
            return;
        }
        boton.setText("⟳  DESCARGANDO DEL PC…");
        new Thread(() -> {
            try {
                JSONObject info = new JSONObject((String) Conexion.post(a, "/app/version_apk", new JSONObject(), 8000)[1]);
                byte[] apk = Conexion.descargar(a, "/app/apk", new JSONObject(), 60_000);
                MessageDigest md = MessageDigest.getInstance("SHA-256");
                StringBuilder hex = new StringBuilder();
                for (byte x : md.digest(apk)) hex.append(String.format("%02x", x));
                if (!hex.toString().equals(info.getString("sha256"))) throw new Exception("la descarga llegó dañada");
                PackageInstaller pi = a.getPackageManager().getPackageInstaller();
                PackageInstaller.SessionParams sp = new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
                sp.setAppPackageName(a.getPackageName());
                int id = pi.createSession(sp);
                try (PackageInstaller.Session s = pi.openSession(id)) {
                    try (OutputStream os = s.openWrite("jarvis.apk", 0, apk.length)) {
                        os.write(apk);
                        s.fsync(os);
                    }
                    Intent aviso = new Intent(a, Actualizador.class);
                    PendingIntent pin = PendingIntent.getBroadcast(a, id, aviso,
                            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_MUTABLE);
                    s.commit(pin.getIntentSender());
                }
                a.runOnUiThread(() -> boton.setText("⟳  CONFIRMA LA INSTALACIÓN…"));
            } catch (Exception e) {
                a.runOnUiThread(() -> {
                    boton.setText("⟳  ACTUALIZAR JARVIS");
                    Toast.makeText(a, "No se pudo actualizar: " + e.getMessage(), Toast.LENGTH_LONG).show();
                });
                Conexion.error(a, "actualizar: " + e.getMessage());
            }
        }, "jarvis-actualizar").start();
    }

    /** Respuesta del instalador: si pide confirmación, se la enseña al dueño; si falla, se cuenta el motivo. */
    @Override
    public void onReceive(Context c, Intent i) {
        int estado = i.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
        if (estado == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            Intent confirmar = i.getParcelableExtra(Intent.EXTRA_INTENT);
            if (confirmar != null) {
                confirmar.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                c.startActivity(confirmar);
            }
        } else if (estado != PackageInstaller.STATUS_SUCCESS) {
            String motivo = i.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE);
            Toast.makeText(c, "La actualización no se instaló: " + motivo, Toast.LENGTH_LONG).show();
            new Thread(() -> Conexion.error(c, "actualizar: estado " + estado + " " + motivo)).start();
        }
    }
}
