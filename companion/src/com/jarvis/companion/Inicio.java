package com.jarvis.companion;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.os.StatFs;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.widget.FrameLayout;
import android.widget.GridLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONObject;

/**
 * Panel principal de JARVIS (estilo HUD, diseño propio): el núcleo animado (tócalo para hablar), tarjetas de
 * estado con luces, la última conversación y los ajustes. Incluye «Actualizar JARVIS» desde el PC.
 */
public class Inicio extends Activity {
    private View[] tPc, tAcc, tFondo, tPalmadas, tBateria, tEspacio;
    private TextView ultima, aviso, bPalmadas, bSensibilidad, bActualizar;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        getWindow().setStatusBarColor(Estilo.FONDO);
        getWindow().setNavigationBarColor(Estilo.FONDO);
        FrameLayout raiz = new FrameLayout(this);
        raiz.addView(new Fondo(this, true), new FrameLayout.LayoutParams(-1, -1));
        ScrollView scroll = new ScrollView(this);
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.VERTICAL);
        int m = Estilo.dp(this, 20);
        l.setPadding(m, m * 2, m, m * 2);
        scroll.addView(l);
        raiz.addView(scroll);

        // Cabecera
        LinearLayout cab = new LinearLayout(this);
        cab.setGravity(Gravity.CENTER_VERTICAL);
        TextView titulo = Estilo.texto(this, "J.A.R.V.I.S.", 24, Estilo.CIAN, true);
        titulo.setShadowLayer(18, 0, 0, Estilo.CIAN);
        cab.addView(titulo, new LinearLayout.LayoutParams(0, -2, 1));
        cab.addView(Estilo.rotulo(this, "v" + Conexion.VERSION));
        l.addView(cab);
        l.addView(Estilo.rotulo(this, "Asistente personal · sistema en línea"));

        // Núcleo: tócalo para hablar
        Reactor reactor = new Reactor(this);
        int lado = (int) (getResources().getDisplayMetrics().widthPixels * 0.62f);
        LinearLayout.LayoutParams lr = new LinearLayout.LayoutParams(lado, lado);
        lr.gravity = Gravity.CENTER_HORIZONTAL;
        lr.setMargins(0, m, 0, 0);
        reactor.setOnClickListener(v -> startActivity(new Intent(this, Escuchar.class)));
        l.addView(reactor, lr);
        TextView toca = Estilo.rotulo(this, "Toca el núcleo para hablar");
        toca.setGravity(Gravity.CENTER);
        l.addView(toca, new LinearLayout.LayoutParams(-1, -2));
        reactor.setScaleX(0.4f);
        reactor.setScaleY(0.4f);
        reactor.setAlpha(0f);
        reactor.animate().scaleX(1f).scaleY(1f).alpha(1f).setDuration(700).start();  // entrada

        aviso = Estilo.texto(this, "", 13, Estilo.AMBAR, true);
        aviso.setPadding(0, m / 2, 0, 0);
        l.addView(aviso);

        // Tarjetas de estado (2 columnas)
        GridLayout g = new GridLayout(this);
        g.setColumnCount(2);
        tPc = tarjeta(g, "Enlace PC");
        tAcc = tarjeta(g, "Accesibilidad");
        tFondo = tarjeta(g, "Segundo plano");
        tPalmadas = tarjeta(g, "Palmadas");
        tBateria = tarjeta(g, "Batería");
        tEspacio = tarjeta(g, "Espacio libre");
        LinearLayout.LayoutParams lg = new LinearLayout.LayoutParams(-1, -2);
        lg.setMargins(0, m / 2, 0, 0);
        l.addView(g, lg);

        // Última conversación
        l.addView(seccion("Última orden"));
        ultima = Estilo.texto(this, "", 13, Estilo.BLANCO, true);
        int p = Estilo.dp(this, 12);
        ultima.setPadding(p, p, p, p);
        ultima.setBackground(Estilo.marco(this, Estilo.CIAN_OSCURO));
        l.addView(ultima);

        // Despertar
        l.addView(seccion("Despertar a JARVIS"));
        l.addView(Estilo.boton(this, "🎙  Hablar ahora", v -> startActivity(new Intent(this, Escuchar.class))));
        l.addView(Estilo.boton(this, "Botón lateral (asistente)", v -> {
            try {
                startActivity(new Intent(Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS));
            } catch (Exception e) {
                startActivity(new Intent(Settings.ACTION_SETTINGS));
            }
        }));
        bPalmadas = Estilo.boton(this, "", v -> alternarPalmadas());
        l.addView(bPalmadas);
        bSensibilidad = Estilo.boton(this, "", v -> {
            int s = Palmadas.sensibilidad(this) % 5 + 1;
            Conexion.prefs(this).edit().putInt("palmadas_sensibilidad", s).apply();
            pintar();
        });
        l.addView(bSensibilidad);

        // Permisos y sistema
        l.addView(seccion("Permisos y sistema"));
        l.addView(Estilo.boton(this, "Permiso de accesibilidad", v -> startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))));
        l.addView(Estilo.boton(this, "Funcionar en segundo plano", v -> pedirSinRestriccionDeBateria()));
        l.addView(Estilo.boton(this, "Probar enlace con el PC", v -> probar()));
        bActualizar = Estilo.boton(this, "⟳  Actualizar JARVIS", v -> Actualizador.empezar(this, bActualizar));
        l.addView(bActualizar);

        TextView pie = Estilo.texto(this, "JARVIS usa el móvil solo cuando tú se lo pides. Lo irreversible (enviar, pagar, "
                + "borrar…) te lo pide antes con un botón en Telegram. Nunca escribe contraseñas.", 11, Estilo.CIAN_TENUE, false);
        pie.setPadding(0, m, 0, 0);
        l.addView(pie);

        setContentView(raiz);
        if (!sinRestriccionDeBateria()) pedirSinRestriccionDeBateria();  // lo pide sola la primera vez
        new Thread(() -> Escuchar.descargarSaludos(this)).start();
    }

    private View[] tarjeta(GridLayout g, String rotulo) {
        View[] t = Estilo.tarjeta(this, rotulo);
        GridLayout.LayoutParams p = new GridLayout.LayoutParams(GridLayout.spec(GridLayout.UNDEFINED, 1f),
                GridLayout.spec(GridLayout.UNDEFINED, 1f));
        p.width = 0;
        int mm = Estilo.dp(this, 3);
        p.setMargins(mm, mm, mm, mm);
        g.addView(t[0], p);
        return t;
    }

    private TextView seccion(String s) {
        TextView t = Estilo.rotulo(this, "▸ " + s);
        t.setTextColor(Estilo.CIAN);
        t.setPadding(0, Estilo.dp(this, 22), 0, Estilo.dp(this, 4));
        return t;
    }

    @Override
    protected void onResume() {
        super.onResume();
        pintar();
        Actualizador.comprobar(this, bActualizar);  // ¿hay versión nueva en el PC?
    }

    private void alternarPalmadas() {
        boolean si = !Palmadas.activadas(this);
        if (si) {
            java.util.List<String> faltan = new java.util.ArrayList<>();
            if (checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) != android.content.pm.PackageManager.PERMISSION_GRANTED)
                faltan.add(android.Manifest.permission.RECORD_AUDIO);
            if (android.os.Build.VERSION.SDK_INT >= 33 && checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)
                    != android.content.pm.PackageManager.PERMISSION_GRANTED)
                faltan.add(android.Manifest.permission.POST_NOTIFICATIONS);
            if (!faltan.isEmpty()) {
                requestPermissions(faltan.toArray(new String[0]), 2);
                return;
            }
        }
        Palmadas.activar(this, si);
        pintar();
    }

    private void probar() {
        aviso.setText("Probando el enlace…");
        new Thread(() -> {
            Object[] r = Conexion.post(this, "/app/hola", new JSONObject(), 8000);
            int codigo = (int) r[0];
            Conexion.anotar(this, codigo == 200 ? "ultimo_contacto" : "ultimo_error",
                    codigo == 200 ? "prueba OK con el PC" : "prueba fallida: " + (codigo == -1 ? r[1] : "el PC respondió " + codigo));
            runOnUiThread(() -> {
                aviso.setText(codigo == 200 ? "✓ Enlace con el PC correcto" : "✗ Sin enlace con el PC");
                pintar();
            });
        }).start();
    }

    private boolean sinRestriccionDeBateria() {
        android.os.PowerManager pm = (android.os.PowerManager) getSystemService(POWER_SERVICE);
        return pm != null && pm.isIgnoringBatteryOptimizations(getPackageName());
    }

    private void pedirSinRestriccionDeBateria() {
        try {
            startActivity(new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                    android.net.Uri.parse("package:" + getPackageName())));
        } catch (Exception e) {
            startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS));
        }
    }

    static long libreMb(android.content.Context c) {
        StatFs s = new StatFs(c.getFilesDir().getAbsolutePath());
        return s.getAvailableBytes() / (1024 * 1024);
    }

    private void poner(View[] t, String valor, int color) {
        ((TextView) t[1]).setText(valor);
        Estilo.luz(t[2], color);
    }

    private void pintar() {
        String activos = Settings.Secure.getString(getContentResolver(), Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
        boolean permiso = activos != null && activos.contains(getPackageName());
        String contacto = Conexion.prefs(this).getString("ultimo_contacto", "");
        poner(tPc, Accesibilidad.activa ? "Activo" : contacto.isEmpty() ? "Sin enlace" : "En pausa",
                Accesibilidad.activa ? Estilo.VERDE : Estilo.ROJO);
        poner(tAcc, permiso ? "Activado" : "Desactivado", permiso ? Estilo.VERDE : Estilo.ROJO);
        poner(tFondo, sinRestriccionDeBateria() ? "Sin límites" : "Limitado", sinRestriccionDeBateria() ? Estilo.VERDE : Estilo.AMBAR);
        poner(tPalmadas, Palmadas.activadas(this) ? "Escuchando" : "Apagadas", Palmadas.activadas(this) ? Estilo.VERDE : Estilo.CIAN_OSCURO);
        android.os.BatteryManager bm = (android.os.BatteryManager) getSystemService(BATTERY_SERVICE);
        int bat = bm == null ? -1 : bm.getIntProperty(android.os.BatteryManager.BATTERY_PROPERTY_CAPACITY);
        poner(tBateria, bat >= 0 ? bat + " %" : "—", bat > 20 ? Estilo.VERDE : Estilo.AMBAR);
        long libre = libreMb(this);
        poner(tEspacio, libre >= 1024 ? String.format(java.util.Locale.ROOT, "%.1f GB", libre / 1024f) : libre + " MB",
                libre >= 1024 ? Estilo.VERDE : libre >= 500 ? Estilo.AMBAR : Estilo.ROJO);
        if (libre < 500) aviso.setText("⚠ Poco espacio libre: Android no podrá instalar actualizaciones. Libera al menos 1 GB.");
        else if (!permiso) aviso.setText("⚠ Activa el permiso de accesibilidad para que JARVIS pueda usar el móvil.");
        else aviso.setText("");
        String u = Conexion.prefs(this).getString("ultima_orden", "");
        ultima.setText(u.isEmpty() ? "› A la espera de órdenes" : u);
        bPalmadas.setText(Palmadas.activadas(this) ? "👏  Palmadas: activadas" : "👏  Activar las dos palmadas");
        bSensibilidad.setText("Sensibilidad de palmadas: " + Palmadas.sensibilidad(this) + " / 5");
    }
}
