package com.jarvis.companion;

import android.accessibilityservice.AccessibilityService;
import android.graphics.PixelFormat;
import android.view.Gravity;
import android.view.WindowManager;

/**
 * La bolita flotante de JARVIS: cuando JARVIS usa otra app, el HUD se aparta y queda este reactor pequeño en el
 * borde, animado (pensando / hablando). No se puede tocar a propósito: así no estorba a los toques de JARVIS.
 */
final class Orbe {
    private static Reactor vista;
    private Orbe() {}

    static void mostrar(AccessibilityService s, int estado) {
        if (s == null) return;
        new android.os.Handler(android.os.Looper.getMainLooper()).post(() -> {
            try {
                if (vista == null) {
                    vista = new Reactor(s);
                    int lado = (int) (s.getResources().getDisplayMetrics().density * 72);
                    WindowManager.LayoutParams p = new WindowManager.LayoutParams(lado, lado,
                            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
                            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
                                    | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
                            PixelFormat.TRANSLUCENT);
                    p.gravity = Gravity.START | Gravity.CENTER_VERTICAL;
                    p.x = (int) (s.getResources().getDisplayMetrics().density * 6);
                    ((WindowManager) s.getSystemService(AccessibilityService.WINDOW_SERVICE)).addView(vista, p);
                }
                vista.estado(estado);
            } catch (Exception e) {
                vista = null;
            }
        });
    }

    static void quitar(AccessibilityService s) {
        if (s == null) return;
        new android.os.Handler(android.os.Looper.getMainLooper()).post(() -> {
            try {
                if (vista != null) ((WindowManager) s.getSystemService(AccessibilityService.WINDOW_SERVICE)).removeView(vista);
            } catch (Exception ignored) {
            }
            vista = null;
        });
    }
}
