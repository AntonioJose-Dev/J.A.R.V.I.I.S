package com.jarvis.companion;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.graphics.Path;
import android.graphics.Rect;
import android.os.Bundle;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.Normalizer;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;

/**
 * "Las manos" de JARVIS en el móvil: ver la pantalla de cualquier app y actuar (tocar, escribir, deslizar,
 * atrás, inicio, abrir apps...). Lo decide JARVIS en el PC paso a paso; lo que no tiene vuelta atrás se
 * confirma antes en Telegram. Nunca escribe en campos de contraseña.
 */
final class Manos {
    private Manos() {}

    /** Los elementos de la última pantalla vista, por número (JARVIS dice "toca el 7"). */
    private static final List<AccessibilityNodeInfo> ultimos = new ArrayList<>();

    static AccessibilityNodeInfo raiz(AccessibilityService s) {
        AccessibilityNodeInfo r = s.getRootInActiveWindow();
        if (r != null) return r;
        try {
            for (AccessibilityWindowInfo w : s.getWindows()) {
                if (w.isActive() && w.getRoot() != null) return w.getRoot();
            }
        } catch (Exception ignored) {
        }
        return null;
    }

    /** La pantalla actual, resumida: app y elementos visibles con número, texto, descripción y qué se puede hacer. */
    static synchronized JSONObject ver(AccessibilityService s) throws Exception {
        ultimos.clear();
        JSONObject res = new JSONObject();
        AccessibilityNodeInfo r = raiz(s);
        if (r == null) {
            return res.put("app", "").put("elementos", new JSONArray()).put("aviso", "no puedo ver la pantalla");
        }
        res.put("app", String.valueOf(r.getPackageName()));
        JSONArray arr = new JSONArray();
        ArrayDeque<AccessibilityNodeInfo> cola = new ArrayDeque<>();
        cola.add(r);
        Rect b = new Rect();
        while (!cola.isEmpty() && arr.length() < 90) {
            AccessibilityNodeInfo x = cola.poll();
            if (x == null) continue;
            for (int i = 0; i < x.getChildCount(); i++) cola.add(x.getChild(i));
            if (!x.isVisibleToUser()) continue;
            CharSequence t = x.getText(), d = x.getContentDescription();
            boolean util = x.isClickable() || x.isLongClickable() || x.isEditable() || x.isScrollable()
                    || (t != null && t.length() > 0) || (d != null && d.length() > 0);
            if (!util) continue;
            x.getBoundsInScreen(b);
            JSONObject e = new JSONObject().put("n", ultimos.size() + 1);
            if (t != null && t.length() > 0) e.put("t", corto(t.toString(), 80));
            if (d != null && d.length() > 0) e.put("d", corto(d.toString(), 80));
            String vid = x.getViewIdResourceName();
            if (vid != null) e.put("id", vid.replaceAll("^.*:id/", ""));
            if (x.isClickable()) e.put("pulsable", true);
            if (x.isEditable()) e.put("escribible", true);
            if (x.isScrollable()) e.put("desplazable", true);
            if (x.isPassword()) e.put("contraseña", true);
            e.put("x", b.centerX()).put("y", b.centerY());
            ultimos.add(x);
            arr.put(e);
        }
        return res.put("elementos", arr);
    }

    private static String corto(String s, int n) {
        s = s.replace('\n', ' ');
        return s.length() > n ? s.substring(0, n) + "…" : s;
    }

    private static AccessibilityNodeInfo elemento(int n) throws Exception {
        if (n < 1 || n > ultimos.size()) throw new Exception("no hay ningún elemento " + n + " en la última pantalla");
        return ultimos.get(n - 1);
    }

    /** Hace una acción. Devuelve una frase de lo hecho (la pantalla nueva la manda quien llama, tras esperar). */
    static synchronized String hacer(AccessibilityService s, JSONObject a) throws Exception {
        String tipo = a.optString("tipo", "ver");
        switch (tipo) {
            case "ver":
                return "miro la pantalla";
            case "tocar":
            case "mantener": {
                AccessibilityNodeInfo x = elemento(a.optInt("n"));
                int accion = tipo.equals("tocar") ? AccessibilityNodeInfo.ACTION_CLICK : AccessibilityNodeInfo.ACTION_LONG_CLICK;
                for (AccessibilityNodeInfo p = x; p != null; p = p.getParent()) {
                    if ((tipo.equals("tocar") && p.isClickable()) || (tipo.equals("mantener") && p.isLongClickable())) {
                        if (p.performAction(accion)) return tipo.equals("tocar") ? "tocado" : "mantenido";
                        break;
                    }
                }
                Rect b = new Rect();
                x.getBoundsInScreen(b);
                gesto(s, b.centerX(), b.centerY(), b.centerX(), b.centerY(), tipo.equals("tocar") ? 60 : 900);
                return (tipo.equals("tocar") ? "tocado" : "mantenido") + " (en su posición)";
            }
            case "escribir": {
                AccessibilityNodeInfo x = a.has("n") && a.optInt("n") > 0 ? elemento(a.optInt("n")) : enfocado(s);
                if (x == null) throw new Exception("no hay ningún campo de texto seleccionado");
                if (x.isPassword()) throw new Exception("es un campo de CONTRASEÑA: eso lo escribe el dueño, nunca JARVIS");
                if (!x.isEditable()) throw new Exception("ese elemento no es un campo de texto");
                x.performAction(AccessibilityNodeInfo.ACTION_FOCUS);
                Bundle args = new Bundle();
                args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, a.optString("texto"));
                if (!x.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) throw new Exception("no me dejó escribir ahí");
                return "escrito";
            }
            case "deslizar": {
                int w = s.getResources().getDisplayMetrics().widthPixels, h = s.getResources().getDisplayMetrics().heightPixels;
                String dir = a.optString("direccion", "abajo");
                int cx = w / 2, cy = h / 2, dx = w / 3, dy = h / 3;
                // "abajo" = ver lo de más abajo (el dedo sube)
                switch (dir) {
                    case "arriba": gesto(s, cx, cy - dy, cx, cy + dy, 350); break;
                    case "izquierda": gesto(s, cx - dx, cy, cx + dx, cy, 300); break;
                    case "derecha": gesto(s, cx + dx, cy, cx - dx, cy, 300); break;
                    default: gesto(s, cx, cy + dy, cx, cy - dy, 350);
                }
                return "deslizado hacia " + dir;
            }
            case "atras": return global(s, AccessibilityService.GLOBAL_ACTION_BACK, "atrás");
            case "inicio": return global(s, AccessibilityService.GLOBAL_ACTION_HOME, "pantalla de inicio");
            case "recientes": return global(s, AccessibilityService.GLOBAL_ACTION_RECENTS, "apps recientes");
            case "notificaciones": return global(s, AccessibilityService.GLOBAL_ACTION_NOTIFICATIONS, "notificaciones");
            case "ajustes_rapidos": return global(s, AccessibilityService.GLOBAL_ACTION_QUICK_SETTINGS, "ajustes rápidos");
            case "bloquear": return global(s, AccessibilityService.GLOBAL_ACTION_LOCK_SCREEN, "móvil bloqueado");
            case "abrir": return abrir(s, a.optString("app"));
            case "captura": return global(s, AccessibilityService.GLOBAL_ACTION_TAKE_SCREENSHOT, "captura de pantalla");
            case "panel": {
                // Wi-Fi, Bluetooth, datos o brillo: se abre su panel (Android no deja cambiarlos sin que lo veas)
                String p = a.optString("panel");
                String accion = p.equals("wifi") ? "android.settings.panel.action.WIFI"
                        : p.equals("datos") ? "android.settings.panel.action.INTERNET_CONNECTIVITY"
                        : p.equals("bluetooth") ? android.provider.Settings.ACTION_BLUETOOTH_SETTINGS
                        : p.equals("brillo") ? android.provider.Settings.ACTION_DISPLAY_SETTINGS
                        : android.provider.Settings.ACTION_SETTINGS;
                s.startActivity(new Intent(accion).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                return "abierto el panel de " + p;
            }
            case "enlace": {
                // Atajo: abre directamente una búsqueda de YouTube, un mapa, Spotify… (mucho más rápido que tocar)
                android.net.Uri u = android.net.Uri.parse(a.optString("url"));
                String esquema = u.getScheme() == null ? "" : u.getScheme().toLowerCase();
                if (!java.util.Arrays.asList("https", "http", "spotify", "geo", "vnd.youtube", "google.navigation").contains(esquema)) {
                    throw new Exception("ese tipo de enlace no lo abro (" + esquema + ")");
                }
                Intent i = new Intent(Intent.ACTION_VIEW, u).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                String paquete = paqueteDe(s, a.optString("app"));  // p. ej. abrirlo en Chrome o en Instagram
                if (paquete != null) i.setPackage(paquete);
                try {
                    s.startActivity(i);
                } catch (android.content.ActivityNotFoundException e) {
                    i.setPackage(null);  // si esa app no lo abre, que lo abra la que toque
                    s.startActivity(i);
                }
                return "abierto " + (u.getHost() != null ? u.getHost() : esquema);
            }
            case "reproducir": {
                // «Pon Queen en Spotify»: la app de música busca y EMPIEZA a sonar sola (sin tocar nada)
                Intent i = new Intent(android.provider.MediaStore.INTENT_ACTION_MEDIA_PLAY_FROM_SEARCH)
                        .putExtra(android.app.SearchManager.QUERY, a.optString("consulta"))
                        .putExtra(android.provider.MediaStore.EXTRA_MEDIA_FOCUS, "vnd.android.cursor.item/*")
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                String paquete = paqueteDe(s, a.optString("app", "Spotify"));
                if (paquete != null) i.setPackage(paquete);
                s.startActivity(i);
                return "reproduciendo «" + a.optString("consulta") + "»";
            }
            case "ajustes": {
                // Una pantalla concreta de Ajustes
                String que = sinAcentos(a.optString("pantalla"));
                String accion = que.contains("wifi") ? android.provider.Settings.ACTION_WIFI_SETTINGS
                        : que.contains("bluetooth") ? android.provider.Settings.ACTION_BLUETOOTH_SETTINGS
                        : que.contains("brillo") || que.contains("pantalla") ? android.provider.Settings.ACTION_DISPLAY_SETTINGS
                        : que.contains("sonido") || que.contains("volumen") ? android.provider.Settings.ACTION_SOUND_SETTINGS
                        : que.contains("bateria") ? Intent.ACTION_POWER_USAGE_SUMMARY
                        : que.contains("aplicacion") || que.contains("apps") ? android.provider.Settings.ACTION_APPLICATION_SETTINGS
                        : que.contains("ubicacion") || que.contains("gps") ? android.provider.Settings.ACTION_LOCATION_SOURCE_SETTINGS
                        : que.contains("notificacion") ? android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS
                        : que.contains("no molestar") ? android.provider.Settings.ACTION_ZEN_MODE_PRIORITY_SETTINGS
                        : que.contains("datos") || que.contains("red") ? android.provider.Settings.ACTION_WIRELESS_SETTINGS
                        : que.contains("almacenamiento") ? android.provider.Settings.ACTION_INTERNAL_STORAGE_SETTINGS
                        : que.contains("accesibilidad") ? android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS
                        : que.contains("idioma") ? android.provider.Settings.ACTION_LOCALE_SETTINGS
                        : que.contains("fecha") || que.contains("hora") ? android.provider.Settings.ACTION_DATE_SETTINGS
                        : android.provider.Settings.ACTION_SETTINGS;
                Intent i = new Intent(accion).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                if (accion.equals(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS)) {
                    i = new Intent(android.provider.Settings.ACTION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                }
                s.startActivity(i);
                return "abiertos los ajustes de " + (que.isEmpty() ? "Android" : que);
            }
            case "media": {
                // Pausa / sigue / siguiente / anterior en CUALQUIER app de música o vídeo (al instante)
                String que = a.optString("tecla", "pausa");
                int tecla = que.equals("siguiente") ? android.view.KeyEvent.KEYCODE_MEDIA_NEXT
                        : que.equals("anterior") ? android.view.KeyEvent.KEYCODE_MEDIA_PREVIOUS
                        : que.equals("play") ? android.view.KeyEvent.KEYCODE_MEDIA_PLAY
                        : que.equals("pausa") ? android.view.KeyEvent.KEYCODE_MEDIA_PAUSE
                        : android.view.KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE;
                android.media.AudioManager am = (android.media.AudioManager) s.getSystemService(AccessibilityService.AUDIO_SERVICE);
                am.dispatchMediaKeyEvent(new android.view.KeyEvent(android.view.KeyEvent.ACTION_DOWN, tecla));
                am.dispatchMediaKeyEvent(new android.view.KeyEvent(android.view.KeyEvent.ACTION_UP, tecla));
                return "música: " + que;
            }
            case "no_molestar": {
                android.app.NotificationManager nm = s.getSystemService(android.app.NotificationManager.class);
                if (!nm.isNotificationPolicyAccessGranted()) {
                    s.startActivity(new Intent(android.provider.Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS)
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                    throw new Exception("falta un permiso de una sola vez: te he abierto la pantalla; activa JARVIS en «Acceso a No molestar»");
                }
                boolean on = !"off".equals(a.optString("estado", "on"));
                nm.setInterruptionFilter(on ? android.app.NotificationManager.INTERRUPTION_FILTER_PRIORITY
                        : android.app.NotificationManager.INTERRUPTION_FILTER_ALL);
                return "no molestar " + (on ? "activado" : "desactivado");
            }
            case "brillo": {
                if (!android.provider.Settings.System.canWrite(s)) {
                    s.startActivity(new Intent(android.provider.Settings.ACTION_MANAGE_WRITE_SETTINGS,
                            android.net.Uri.parse("package:" + s.getPackageName())).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                    throw new Exception("falta un permiso de una sola vez: te he abierto la pantalla; activa «Modificar ajustes del sistema»");
                }
                int pct = Math.max(1, Math.min(100, a.optInt("nivel", 50)));
                android.content.ContentResolver cr = s.getContentResolver();
                android.provider.Settings.System.putInt(cr, android.provider.Settings.System.SCREEN_BRIGHTNESS_MODE,
                        android.provider.Settings.System.SCREEN_BRIGHTNESS_MODE_MANUAL);
                android.provider.Settings.System.putInt(cr, android.provider.Settings.System.SCREEN_BRIGHTNESS, pct * 255 / 100);
                return "brillo al " + pct + " %";
            }
            case "tocar_texto": {
                // Toca el elemento visible que dice ese texto (o su descripción): JARVIS no tiene que adivinar números
                AccessibilityNodeInfo x = buscarTexto(s, a.optString("texto"));
                if (x == null) throw new Exception("no veo nada que diga «" + a.optString("texto") + "» en la pantalla");
                for (AccessibilityNodeInfo p = x; p != null; p = p.getParent()) {
                    if (p.isClickable()) {
                        if (p.performAction(AccessibilityNodeInfo.ACTION_CLICK)) return "tocado «" + a.optString("texto") + "»";
                        break;
                    }
                }
                Rect b = new Rect();
                x.getBoundsInScreen(b);
                gesto(s, b.centerX(), b.centerY(), b.centerX(), b.centerY(), 60);
                return "tocado «" + a.optString("texto") + "» (en su posición)";
            }
            case "cerrar": {
                // Android no deja a otra app "matar" una app; se sale de ella (atrás y a inicio)
                s.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK);
                s.performGlobalAction(AccessibilityService.GLOBAL_ACTION_HOME);
                return "he salido de la app (Android no deja cerrarla del todo desde otra app)";
            }
            default:
                throw new Exception("no sé hacer «" + tipo + "»");
        }
    }

    private static String global(AccessibilityService s, int accion, String que) throws Exception {
        if (!s.performGlobalAction(accion)) throw new Exception("Android no me dejó: " + que);
        return que;
    }

    private static AccessibilityNodeInfo enfocado(AccessibilityService s) {
        AccessibilityNodeInfo r = raiz(s);
        return r == null ? null : r.findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
    }

    private static void gesto(AccessibilityService s, float x1, float y1, float x2, float y2, long ms) {
        Path p = new Path();
        p.moveTo(x1, y1);
        if (x1 != x2 || y1 != y2) p.lineTo(x2, y2);
        s.dispatchGesture(new GestureDescription.Builder()
                .addStroke(new GestureDescription.StrokeDescription(p, 0, ms)).build(), null, null);
    }

    private static String sinAcentos(String s) {
        return Normalizer.normalize(s == null ? "" : s, Normalizer.Form.NFD).replaceAll("\\p{M}", "").toLowerCase().trim();
    }

    /** El nodo visible cuyo texto o descripción coincide (primero exacto, luego «contiene»). */
    private static AccessibilityNodeInfo buscarTexto(AccessibilityService s, String texto) {
        String buscado = sinAcentos(texto);
        if (buscado.isEmpty()) return null;
        AccessibilityNodeInfo r = raiz(s);
        if (r == null) return null;
        AccessibilityNodeInfo contiene = null;
        ArrayDeque<AccessibilityNodeInfo> cola = new ArrayDeque<>();
        cola.add(r);
        while (!cola.isEmpty()) {
            AccessibilityNodeInfo x = cola.poll();
            if (x == null) continue;
            for (int i = 0; i < x.getChildCount(); i++) cola.add(x.getChild(i));
            if (!x.isVisibleToUser()) continue;
            for (CharSequence cs : new CharSequence[]{x.getText(), x.getContentDescription()}) {
                if (cs == null) continue;
                String t = sinAcentos(cs.toString());
                if (t.equals(buscado)) return x;
                if (contiene == null && t.contains(buscado) && t.length() < buscado.length() * 4 + 20) contiene = x;
            }
        }
        return contiene;
    }

    /** El paquete de una app por su nombre («Chrome», «Spotify»…) o null si no se dijo o no está. */
    private static String paqueteDe(AccessibilityService s, String nombre) {
        if (nombre == null || nombre.trim().isEmpty()) return null;
        if (nombre.contains(".")) return nombre;
        PackageManager pm = s.getPackageManager();
        String buscado = sinAcentos(nombre);
        for (ResolveInfo ri : pm.queryIntentActivities(new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0)) {
            String et = sinAcentos(String.valueOf(ri.loadLabel(pm)));
            if (et.equals(buscado) || et.contains(buscado)) return ri.activityInfo.packageName;
        }
        return null;
    }

    /** Abre una app por su nombre ("YouTube", "notas") o su paquete. */
    private static String abrir(AccessibilityService s, String nombre) throws Exception {
        PackageManager pm = s.getPackageManager();
        Intent lanzador = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER);
        List<ResolveInfo> apps = pm.queryIntentActivities(lanzador, 0);
        String buscado = sinAcentos(nombre);
        ResolveInfo mejor = null;
        for (ResolveInfo ri : apps) {
            String etiqueta = sinAcentos(String.valueOf(ri.loadLabel(pm)));
            String paquete = ri.activityInfo.packageName;
            if (etiqueta.equals(buscado) || paquete.equals(nombre)) {
                mejor = ri;
                break;
            }
            if (mejor == null && (etiqueta.contains(buscado) || buscado.contains(etiqueta) && etiqueta.length() > 2)) mejor = ri;
        }
        if (mejor == null) throw new Exception("no encuentro ninguna app llamada «" + nombre + "»");
        Intent i = pm.getLaunchIntentForPackage(mejor.activityInfo.packageName);
        if (i == null) throw new Exception("esa app no se puede abrir");
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        s.startActivity(i);
        return "abierta " + mejor.loadLabel(pm);
    }
}
