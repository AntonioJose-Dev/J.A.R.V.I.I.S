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
import android.view.View;
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
    /** La pantalla abierta (si la hay): el servicio la aparta cuando JARVIS tiene que usar el móvil. */
    static volatile Escuchar abierta = null;

    static void apartar() {
        Escuchar e = abierta;
        if (e == null) return;
        e.apartada = true;
        e.runOnUiThread(() -> e.moveTaskToBack(true));
        Orbe.mostrar(Accesibilidad.instancia, Reactor.PENSANDO);  // queda la bolita, animada, en el borde
    }

    // --- Panel de pasos: lo que JARVIS va haciendo («📱 Abriendo YouTube ✓») -----------------------------
    private final java.util.LinkedHashMap<Long, String> pasos = new java.util.LinkedHashMap<>();
    private volatile boolean apartada = false;

    static void anotarPaso(long id, String texto) {
        Escuchar e = abierta;
        if (e == null) return;
        synchronized (e.pasos) {
            e.pasos.put(id, texto + "  …");
        }
        e.pintarPasos();
    }

    static void marcarPaso(long id, boolean bien) {
        Escuchar e = abierta;
        if (e == null) return;
        synchronized (e.pasos) {
            String t = e.pasos.get(id);
            if (t == null) return;
            e.pasos.put(id, t.replace("  …", bien ? "  ✓" : "  ✗"));
        }
        e.pintarPasos();
    }

    private void pintarPasos() {
        StringBuilder sb = new StringBuilder();
        synchronized (pasos) {
            java.util.List<String> lista = new java.util.ArrayList<>(pasos.values());
            for (String s : lista.subList(Math.max(0, lista.size() - 6), lista.size())) sb.append(s).append("\n");
        }
        runOnUiThread(() -> listaPasos.setText(sb.toString().trim()));
    }

    private Reactor reactor;
    private TextView fase, transcripcion, reloj, sistema, listaPasos;
    private Onda onda;
    private static final int CIAN = Color.parseColor("#4FD8FF");
    private static final int CIAN_TENUE = Color.parseColor("#7FB8CC");

    private TextView texto(float tam, int color, boolean mono) {
        TextView t = new TextView(this);
        t.setTextSize(tam);
        t.setTextColor(color);
        if (mono) t.setTypeface(android.graphics.Typeface.MONOSPACE);
        t.setLetterSpacing(0.12f);
        return t;
    }

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        // HUD: capa oscura translúcida sobre lo que tengas abierto, con el reactor en el centro
        android.widget.FrameLayout raiz = new android.widget.FrameLayout(this);
        raiz.setBackgroundColor(Color.parseColor("#E8020A12"));
        raiz.addView(new Fondo(this, false), new android.widget.FrameLayout.LayoutParams(-1, -1));  // rejilla, visor, escaneo
        int ancho = getResources().getDisplayMetrics().widthPixels;
        int m = (int) (ancho * 0.05f);

        LinearLayout arribaIzq = new LinearLayout(this);
        arribaIzq.setOrientation(LinearLayout.VERTICAL);
        TextView titulo = texto(22, CIAN, true);
        titulo.setText("J.A.R.V.I.S.");
        titulo.setShadowLayer(18, 0, 0, CIAN);
        sistema = texto(10, CIAN_TENUE, true);
        arribaIzq.addView(titulo);
        arribaIzq.addView(sistema);
        android.widget.FrameLayout.LayoutParams p1 = new android.widget.FrameLayout.LayoutParams(-2, -2, Gravity.TOP | Gravity.START);
        p1.setMargins(m, m * 2, m, m);
        raiz.addView(arribaIzq, p1);

        reloj = texto(11, CIAN_TENUE, true);
        reloj.setGravity(Gravity.END);
        android.widget.FrameLayout.LayoutParams p2 = new android.widget.FrameLayout.LayoutParams(-2, -2, Gravity.TOP | Gravity.END);
        p2.setMargins(m, m * 2, m, m);
        raiz.addView(reloj, p2);

        LinearLayout centro = new LinearLayout(this);
        centro.setOrientation(LinearLayout.VERTICAL);
        centro.setGravity(Gravity.CENTER_HORIZONTAL);
        reactor = new Reactor(this);
        centro.addView(reactor, new LinearLayout.LayoutParams((int) (ancho * 0.74f), (int) (ancho * 0.74f)));
        fase = texto(13, CIAN, true);
        fase.setGravity(Gravity.CENTER);
        fase.setShadowLayer(12, 0, 0, CIAN);
        fase.setPadding(0, m / 3, 0, m / 3);
        centro.addView(fase);
        onda = new Onda(this);  // la onda de voz
        LinearLayout.LayoutParams lo = new LinearLayout.LayoutParams((int) (ancho * 0.7f), Estilo.dp(this, 36));
        lo.gravity = Gravity.CENTER_HORIZONTAL;
        centro.addView(onda, lo);
        transcripcion = texto(14, Color.parseColor("#E6F7FF"), true);
        transcripcion.setLetterSpacing(0.02f);
        transcripcion.setGravity(Gravity.CENTER);
        transcripcion.setPadding(m, m / 2, m, 0);
        centro.addView(transcripcion);
        // Registro de operaciones: siempre visible, con su marco
        LinearLayout registro = new LinearLayout(this);
        registro.setOrientation(LinearLayout.VERTICAL);
        registro.setBackground(Estilo.marco(this, Estilo.CIAN_OSCURO));
        int pr = Estilo.dp(this, 10);
        registro.setPadding(pr, pr, pr, pr);
        registro.addView(Estilo.rotulo(this, "Registro de operaciones"));
        listaPasos = texto(12, Color.parseColor("#7CFFB2"), true);  // en verde terminal
        listaPasos.setLetterSpacing(0.04f);
        listaPasos.setText("› A la espera de órdenes");
        listaPasos.setPadding(0, Estilo.dp(this, 4), 0, 0);
        registro.addView(listaPasos);
        LinearLayout.LayoutParams lreg = new LinearLayout.LayoutParams(-1, -2);
        lreg.setMargins(m, m / 2, m, 0);
        centro.addView(registro, lreg);
        raiz.addView(centro, new android.widget.FrameLayout.LayoutParams(-1, -2, Gravity.CENTER));

        setContentView(raiz);
        raiz.setAlpha(0f);
        raiz.animate().alpha(1f).setDuration(300).start();  // aparece suave…
        reactor.setScaleX(0.3f);
        reactor.setScaleY(0.3f);
        reactor.setRotation(-90f);
        reactor.animate().scaleX(1f).scaleY(1f).rotation(0f).setDuration(650)
                .setInterpolator(new android.view.animation.OvershootInterpolator(1.2f)).start();  // …y el núcleo se despliega
        actualizarHud();
        abierta = this;
        estado = transcripcion;
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
        if (abierta == this) abierta = null;
        Orbe.quitar(Accesibilidad.instancia);  // fuera la bolita
        Palmadas.pausado = false;  // las palmadas vuelven a escuchar
        super.onDestroy();
    }

    private void poner(String s) {
        runOnUiThread(() -> estado.setText(s));
    }

    /** Estado del reactor y rótulo (ESCUCHANDO, PROCESANDO, RESPONDIENDO…). */
    private void fase(int e, String rotulo) {
        runOnUiThread(() -> {
            reactor.estado(e);
            fase.setText(rotulo);
        });
        if (apartada) Orbe.mostrar(Accesibilidad.instancia, e);  // la bolita también piensa / habla
    }

    /** La respuesta de JARVIS se escribe letra a letra, como en una consola. */
    private void escribir(String cabecera, String frase) {
        runOnUiThread(() -> {
            final StringBuilder sb = new StringBuilder();
            final android.os.Handler h = new android.os.Handler(android.os.Looper.getMainLooper());
            final int[] i = {0};
            h.post(new Runnable() {
                @Override
                public void run() {
                    if (i[0] < frase.length()) {
                        sb.append(frase.charAt(i[0]++));
                        transcripcion.setText(cabecera + sb + "▌");
                        h.postDelayed(this, 18);
                    } else {
                        transcripcion.setText(cabecera + sb);
                    }
                }
            });
        });
    }

    /** Esquinas del HUD: hora, fecha, batería y enlace con el PC (se refrescan cada segundo). */
    private void actualizarHud() {
        java.util.Date ahora = new java.util.Date();
        reloj.setText(new java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.ROOT).format(ahora) + "\n"
                + new java.text.SimpleDateFormat("EEE dd MMM yyyy", new java.util.Locale("es", "ES")).format(ahora).toUpperCase());
        android.os.BatteryManager bm = (android.os.BatteryManager) getSystemService(BATTERY_SERVICE);
        int bat = bm == null ? -1 : bm.getIntProperty(android.os.BatteryManager.BATTERY_PROPERTY_CAPACITY);
        String enlace = Accesibilidad.activa ? "ENLACE PC ▪ ACTIVO" : "ENLACE PC ▪ —";
        sistema.setText("SISTEMA EN LÍNEA\n" + enlace + "\nENERGÍA ▪ " + (bat >= 0 ? bat + "%" : "—")
                + (Palmadas.corriendo ? "\nSENSOR ACÚSTICO ▪ ON" : ""));
        if (activo) reloj.postDelayed(this::actualizarHud, 1000);
    }

    private void empezar() {
        Palmadas.pausado = true;  // el micrófono es para escucharte a ti
        new Thread(() -> {
            try {
                Thread.sleep(Palmadas.corriendo ? 400 : 0);  // que el detector de palmadas suelte el micrófono
            } catch (InterruptedException ignored) {
            }
            fase(Reactor.HABLANDO, "EN LÍNEA");
            saludar();  // "¿Sí, señor? Aquí estoy." con su voz, al instante (guardado en el móvil)
            // Conversación: tras cada respuesta sigue escuchando; si no dices nada en unos segundos, se cierra
            for (int vuelta = 0; vuelta < 8 && activo; vuelta++) {
                fase(Reactor.ESCUCHANDO, "● ESCUCHANDO");
                if (vuelta > 0) poner("¿Algo más, señor?");
                if (vuelta > 0) pitido();
                byte[] wav = grabar();
                runOnUiThread(() -> reactor.nivel(0));
                if (wav == null) {
                    poner(vuelta == 0 ? "No le he oído. Vuelva a intentarlo." : "A su servicio, señor.");
                    break;
                }
                fase(Reactor.PENSANDO, "PROCESANDO…");
                // La pantalla se queda; solo se aparta si JARVIS necesita usar el móvil (lo avisa el servicio)
                try {
                    // Si tarda, «Un momento, señor» (guardado en el móvil), para que no parezca que no oye
                    final boolean[] llego = {false};
                    new Thread(() -> {
                        try {
                            Thread.sleep(2500);
                        } catch (InterruptedException ignored) {
                        }
                        File momento = new File(getFilesDir(), "saludo3.ogg");
                        if (!llego[0] && momento.length() > 0) reproducirArchivo(momento);
                    }, "jarvis-momento").start();
                    JSONObject r = enviar(wav);
                    llego[0] = true;
                    fase(Reactor.HABLANDO, "RESPONDIENDO");
                    escribir("› " + r.optString("entendido") + "\n\n", r.optString("respuesta"));
                    Conexion.prefs(this).edit().putString("ultima_orden", "› " + r.optString("entendido") + "\n‹ "
                            + r.optString("respuesta")).apply();  // para el panel principal
                    String audio = r.optString("audio");
                    onda.hablando(true);  // la onda se mueve mientras habla JARVIS
                    if (!audio.isEmpty()) reproducir(Base64.decode(audio, Base64.DEFAULT));
                    onda.hablando(false);
                } catch (Exception e) {
                    poner("No he podido hablar con JARVIS: " + e.getMessage());
                    Conexion.error(this, "botón JARVIS: " + e.getMessage());
                    break;
                }
                // Si la pantalla se apartó (JARVIS usó el móvil), solo se puede seguir escuchando con las palmadas activas
                if (!hasWindowFocus() && !Palmadas.corriendo) break;
            }
            Palmadas.pausado = false;
            fase(Reactor.ESPERA, "EN ESPERA");
            cerrarEn(1200);
        }, "jarvis-escuchar").start();
    }

    private void pitido() {
        try {
            new ToneGenerator(AudioManager.STREAM_MUSIC, 70).startTone(ToneGenerator.TONE_PROP_BEEP, 120);
            Thread.sleep(300);  // que acabe ANTES de medir el ruido (si no, todo parecía silencio)
        } catch (Exception ignored) {
        }
    }

    /** Pone uno de los saludos guardados (van rotando). Si aún no están, pitido y se descargan para la próxima. */
    private void saludar() {
        int n = Conexion.prefs(this).getInt("saludo_n", 0);
        Conexion.prefs(this).edit().putInt("saludo_n", (n + 1) % 3).apply();
        File f = new File(getFilesDir(), "saludo" + n + ".ogg");
        if (f.length() > 0) {
            reproducirArchivo(f);
            try {
                Thread.sleep(150);
            } catch (InterruptedException ignored) {
            }
        } else {
            pitido();
            new Thread(() -> descargarSaludos(this), "jarvis-saludos").start();
        }
    }

    /** Descarga los saludos con la voz de JARVIS (una vez) para ponerlos al instante, sin esperar a la red. */
    static void descargarSaludos(android.content.Context c) {
        for (int i = 0; i < 4; i++) {  // 3 saludos + «Un momento, señor»
            File f = new File(c.getFilesDir(), "saludo" + i + ".ogg");
            if (f.length() > 0) continue;
            try {
                byte[] ogg = Conexion.descargar(c, "/app/saludo", new JSONObject().put("n", i), 30_000);
                try (FileOutputStream fo = new FileOutputStream(f)) {
                    fo.write(ogg);
                }
            } catch (Exception e) {
                return;
            }
        }
    }

    private void cerrarEn(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException ignored) {
        }
        runOnUiThread(this::finish);
    }

    /** Graba hasta que te callas (1,6 s de silencio tras hablar), máx. 15 s. Devuelve WAV o null si no hablaste. */
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
            final float nv = (float) Math.min(1.0, rms / 2500.0);
            runOnUiThread(() -> reactor.nivel(nv));  // el reactor late con tu voz
            onda.nivel(nv);
            if (total <= 3) {  // los primeros 300 ms miden el ruido de fondo
                fondo = fondo < 0 ? rms : (fondo + rms) / 2;
            }
            byte[] bytes = new byte[n * 2];
            for (int i = 0; i < n; i++) {
                bytes[2 * i] = (byte) (trozo[i] & 0xff);
                bytes[2 * i + 1] = (byte) ((trozo[i] >> 8) & 0xff);
            }
            pcm.write(bytes, 0, bytes.length);
            double umbral = Math.max(300, Math.min(fondo, 1500) * 2.0);
            if (total > 3 && rms > umbral) {
                hablo = true;
                silencio = 0;
            } else if (hablo) {
                silencio++;
                if (silencio >= 16) break;  // 1,6 s callado: ha terminado
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
            reproducirArchivo(f);
        } catch (Exception e) {
            poner("No pude reproducir la respuesta: " + e.getMessage());
        }
    }

    /** Reproduce y espera a que termine. */
    private void reproducirArchivo(File f) {
        try {
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
