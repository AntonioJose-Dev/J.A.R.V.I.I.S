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
                s.startActivity(i);
                return "abierto " + u.getHost();
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
