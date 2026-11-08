package com.jarvis.companion;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.Build;
import android.os.IBinder;

/**
 * Despertar a JARVIS con dos palmadas. Escucha el micrófono SOLO para detectar dos golpes secos seguidos
 * (no graba ni manda nada a ningún sitio). Al detectarlas, abre «Hablar con JARVIS».
 * Android muestra siempre el aviso y el puntito verde del micrófono mientras está activo, y gasta algo de batería.
 */
public class Palmadas extends Service {
    static volatile boolean pausado = false;   // «Hablar con JARVIS» usa el micrófono: mientras, no se escucha aquí
    static volatile boolean corriendo = false;
    private volatile boolean seguir = false;
    private static final int TASA = 16000;
    private static final int TROZO = TASA / 50;  // 20 ms

    static boolean activadas(Context c) {
        return Conexion.prefs(c).getBoolean("palmadas", false);
    }

    static void activar(Context c, boolean si) {
        Conexion.prefs(c).edit().putBoolean("palmadas", si).apply();
        Intent i = new Intent(c, Palmadas.class);
        if (si) c.startForegroundService(i);
        else c.stopService(i);
    }

    /** Sensibilidad 1 (pocas falsas alarmas) a 5 (detecta palmadas flojas). */
    static int sensibilidad(Context c) {
        return Conexion.prefs(c).getInt("palmadas_sensibilidad", 3);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        NotificationManager nm = getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel("palmadas", "JARVIS escuchando palmadas",
                NotificationManager.IMPORTANCE_LOW));
        PendingIntent abrir = PendingIntent.getActivity(this, 0, new Intent(this, Inicio.class),
                PendingIntent.FLAG_IMMUTABLE);
        Notification n = new Notification.Builder(this, "palmadas")
                .setContentTitle("JARVIS: da dos palmadas para hablarme")
                .setContentText("Solo detecto palmadas; no grabo nada. Tócame para desactivarlo.")
                .setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .setContentIntent(abrir)
                .setOngoing(true)
                .build();
        if (Build.VERSION.SDK_INT >= 30) {
            startForeground(7, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE);
        } else {
            startForeground(7, n);
        }
        if (!seguir) {
            seguir = true;
            new Thread(this::escuchar, "jarvis-palmadas").start();
        }
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        seguir = false;
        corriendo = false;
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent i) {
        return null;
    }

    private void escuchar() {
        corriendo = true;
        AudioRecord rec = null;
        double fondo = 300;
        long primera = 0, ultimoGolpe = 0, despertado = 0;
        short[] buf = new short[TROZO];
        double rmsAnterior = 0;
        while (seguir) {
            if (pausado) {
                if (rec != null) {
                    rec.stop();
                    rec.release();
                    rec = null;
                }
                dormir(300);
                continue;
            }
            if (rec == null) {
                try {
                    int min = AudioRecord.getMinBufferSize(TASA, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
                    rec = new AudioRecord(MediaRecorder.AudioSource.MIC, TASA, AudioFormat.CHANNEL_IN_MONO,
                            AudioFormat.ENCODING_PCM_16BIT, Math.max(min, TROZO * 4));
                    rec.startRecording();
                } catch (Exception e) {
                    Conexion.error(this, "palmadas: no puedo usar el micrófono (" + e.getMessage() + ")");
                    dormir(5000);
                    rec = null;
                    continue;
                }
            }
            int n = rec.read(buf, 0, buf.length);
            if (n <= 0) continue;
            int pico = 0;
            double suma = 0;
            for (int i = 0; i < n; i++) {
                int v = Math.abs(buf[i]);
                if (v > pico) pico = v;
                suma += (double) buf[i] * buf[i];
            }
            double rms = Math.sqrt(suma / n);
            long ahora = System.currentTimeMillis();
            // Una palmada: subida brusca (mucho más que el ruido y que el trozo anterior) y pico alto
            int s = sensibilidad(this);
            double factor = 9 - s;               // 8 (poco sensible) … 4 (muy sensible)
            int picoMin = 14000 - 2000 * s;      // 12000 … 4000
            boolean golpe = pico > picoMin && rms > fondo * factor && rms > rmsAnterior * 3 && ahora - ultimoGolpe > 120;
            if (golpe) {
                ultimoGolpe = ahora;
                if (primera > 0 && ahora - primera >= 150 && ahora - primera <= 700 && ahora - despertado > 4000) {
                    despertado = ahora;
                    primera = 0;
                    despertar();
                } else {
                    primera = ahora;
                }
            } else {
                fondo = fondo * 0.98 + rms * 0.02;  // el ruido de fondo se va ajustando poco a poco
                if (primera > 0 && ahora - primera > 700) primera = 0;
            }
            rmsAnterior = rms;
        }
        if (rec != null) {
            rec.stop();
            rec.release();
        }
        corriendo = false;
    }

    private void despertar() {
        Intent i = new Intent(this, Escuchar.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            startActivity(i);
        } catch (Exception e) {
            Conexion.error(this, "palmadas: no pude abrir «Hablar con JARVIS» (" + e.getMessage() + ")");
        }
    }

    private static void dormir(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException ignored) {
        }
    }
}
