package com.jarvis.companion;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaPlayer;
import android.media.MediaRecorder;
import android.media.ToneGenerator;
import android.media.AudioManager;
import android.os.Bundle;
import android.util.Base64;
import android.view.Gravity;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * "Oye JARVIS" con el botón lateral (asistente del móvil): pita, te escucha hasta que te callas, se lo manda a
 * JARVIS en el PC y pone su respuesta con su voz. Mientras JARVIS usa el móvil, esta pantalla se aparta.
 */
public class Escuchar extends Activity {
    private static final int TASA = 16000;
    private TextView estado;
    private volatile boolean activo = true;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.VERTICAL);
        l.setGravity(Gravity.CENTER);
        l.setPadding(48, 48, 48, 48);
        l.setBackgroundColor(Color.parseColor("#E6101820"));
        TextView titulo = new TextView(this);
        titulo.setText("J.A.R.V.I.S.");
        titulo.setTextColor(Color.parseColor("#4FC3F7"));
        titulo.setTextSize(30);
        titulo.setGravity(Gravity.CENTER);
        estado = new TextView(this);
        estado.setTextColor(Color.WHITE);
        estado.setTextSize(18);
        estado.setGravity(Gravity.CENTER);
        estado.setPadding(0, 40, 0, 0);
        l.addView(titulo);
        l.addView(estado);
        setContentView(l);
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            estado.setText("Necesito permiso para usar el micrófono");
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 1);
        } else {
            empezar();
        }
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] p, int[] r) {
        if (r.length > 0 && r[0] == PackageManager.PERMISSION_GRANTED) empezar();
        else estado.setText("Sin permiso de micrófono no puedo escucharte.");
    }

    @Override
    protected void onDestroy() {
        activo = false;
        Palmadas.pausado = false;  // las palmadas vuelven a escuchar
        super.onDestroy();
    }

    private void poner(String s) {
        runOnUiThread(() -> estado.setText(s));
    }

    private void empezar() {
        Palmadas.pausado = true;  // el micrófono es para escucharte a ti
        new Thread(() -> {
            try {
                Thread.sleep(Palmadas.corriendo ? 400 : 0);  // que el detector de palmadas suelte el micrófono
            } catch (InterruptedException ignored) {
            }
            try {
                new ToneGenerator(AudioManager.STREAM_MUSIC, 80).startTone(ToneGenerator.TONE_PROP_BEEP, 150);
            } catch (Exception ignored) {
            }
            poner("Le escucho, señor…");
            byte[] wav = grabar();
            Palmadas.pausado = false;
            if (wav == null) {
                poner("No le he oído. Vuelva a intentarlo.");
                cerrarEn(1500);
                return;
            }
            poner("Pensando…");
            // JARVIS puede necesitar usar el móvil: esta pantalla se aparta (la respuesta suena igual)
            runOnUiThread(() -> moveTaskToBack(true));
            try {
                JSONObject r = enviar(wav);
                poner("Usted: " + r.optString("entendido") + "\n\nJARVIS: " + r.optString("respuesta"));
                String audio = r.optString("audio");
                if (!audio.isEmpty()) reproducir(Base64.decode(audio, Base64.DEFAULT));
            } catch (Exception e) {
                poner("No he podido hablar con JARVIS: " + e.getMessage());
                Conexion.error(this, "botón JARVIS: " + e.getMessage());
            }
            cerrarEn(800);
        }, "jarvis-escuchar").start();
    }

    private void cerrarEn(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException ignored) {
        }
        runOnUiThread(this::finish);
    }

    /** Graba hasta que te callas (1,2 s de silencio tras hablar), máx. 15 s. Devuelve WAV o null si no hablaste. */
    private byte[] grabar() {
        int min = AudioRecord.getMinBufferSize(TASA, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        AudioRecord rec;
        try {
            rec = new AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, TASA, AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT, Math.max(min, TASA));
            rec.startRecording();
        } catch (SecurityException e) {
            return null;
        }
        ByteArrayOutputStream pcm = new ByteArrayOutputStream();
        short[] trozo = new short[TASA / 10];  // 100 ms
        double fondo = -1;
        boolean hablo = false;
        int silencio = 0, total = 0;
        while (activo && total < 150) {
            int n = rec.read(trozo, 0, trozo.length);
            if (n <= 0) break;
            total++;
            double suma = 0;
            for (int i = 0; i < n; i++) suma += (double) trozo[i] * trozo[i];
            double rms = Math.sqrt(suma / n);
            if (total <= 3) {  // los primeros 300 ms miden el ruido de fondo
                fondo = fondo < 0 ? rms : (fondo + rms) / 2;
            }
            byte[] bytes = new byte[n * 2];
            for (int i = 0; i < n; i++) {
                bytes[2 * i] = (byte) (trozo[i] & 0xff);
                bytes[2 * i + 1] = (byte) ((trozo[i] >> 8) & 0xff);
            }
            pcm.write(bytes, 0, bytes.length);
            double umbral = Math.max(350, fondo * 2.5);
            if (total > 3 && rms > umbral) {
                hablo = true;
                silencio = 0;
            } else if (hablo) {
                silencio++;
                if (silencio >= 12) break;
            } else if (total > 60) {
                break;  // 6 s sin decir nada
            }
        }
        rec.stop();
        rec.release();
        return hablo ? wav(pcm.toByteArray()) : null;
    }

    private static byte[] wav(byte[] pcm) {
        ByteArrayOutputStream o = new ByteArrayOutputStream();
        int datos = pcm.length;
        escribir(o, "RIFF");
        entero(o, 36 + datos);
        escribir(o, "WAVEfmt ");
        entero(o, 16);
        corto(o, 1);
        corto(o, 1);
        entero(o, TASA);
        entero(o, TASA * 2);
        corto(o, 2);
        corto(o, 16);
        escribir(o, "data");
        entero(o, datos);
        o.write(pcm, 0, pcm.length);
        return o.toByteArray();
    }

    private static void escribir(ByteArrayOutputStream o, String s) {
        byte[] b = s.getBytes();
        o.write(b, 0, b.length);
    }

    private static void entero(ByteArrayOutputStream o, int v) {
        o.write(v & 0xff);
        o.write((v >> 8) & 0xff);
        o.write((v >> 16) & 0xff);
        o.write((v >> 24) & 0xff);
    }

    private static void corto(ByteArrayOutputStream o, int v) {
        o.write(v & 0xff);
        o.write((v >> 8) & 0xff);
    }

    private JSONObject enviar(byte[] wav) throws Exception {
        HttpURLConnection con = (HttpURLConnection) new URL(getString(R.string.servidor_jarvis) + "/app/voz").openConnection();
        con.setRequestMethod("POST");
        con.setConnectTimeout(8000);
        con.setReadTimeout(180_000);  // JARVIS puede tardar si tiene que usar el móvil varios pasos
        con.setDoOutput(true);
        con.setRequestProperty("Content-Type", "audio/wav");
        con.setRequestProperty("X-Jarvis-Token", getString(R.string.token_jarvis));
        try (OutputStream os = con.getOutputStream()) {
            os.write(wav);
        }
        int codigo = con.getResponseCode();
        InputStream in = codigo < 400 ? con.getInputStream() : con.getErrorStream();
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        byte[] buf = new byte[16384];
        int n;
        while (in != null && (n = in.read(buf)) > 0) b.write(buf, 0, n);
        con.disconnect();
        JSONObject r = new JSONObject(b.toString("UTF-8"));
        if (codigo != 200) throw new Exception(r.optString("error", "el PC respondió " + codigo));
        return r;
    }

    private void reproducir(byte[] ogg) {
        try {
            File f = new File(getCacheDir(), "respuesta.ogg");
            try (FileOutputStream fo = new FileOutputStream(f)) {
                fo.write(ogg);
            }
            MediaPlayer mp = new MediaPlayer();
            mp.setDataSource(f.getAbsolutePath());
            mp.prepare();
            final Object fin = new Object();
            mp.setOnCompletionListener(x -> {
                synchronized (fin) {
                    fin.notifyAll();
                }
            });
            mp.start();
            synchronized (fin) {
                fin.wait(mp.getDuration() + 2000L);
            }
            mp.release();
        } catch (Exception e) {
            poner("No pude reproducir la respuesta: " + e.getMessage());
        }
    }
}
