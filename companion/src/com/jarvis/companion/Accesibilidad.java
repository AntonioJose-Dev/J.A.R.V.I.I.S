package com.jarvis.companion;

import android.accessibilityservice.AccessibilityService;
import android.os.Handler;
import android.os.Looper;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import java.util.List;

/**
 * Pulsa "Enviar" en WhatsApp, pero SOLO si:
 *  - el agente de JARVIS tiene una orden confirmada por el dueño y firmada (menos de 60 s), y
 *  - el texto que hay escrito en el chat es exactamente el de la orden.
 * Cualquier otro caso: no hace nada. No lee ni guarda los chats.
 */
public class Accesibilidad extends AccessibilityService {
    private static final String[] CAMPOS = {"com.whatsapp:id/entry", "com.whatsapp.w4b:id/entry"};
    private static final String[] ENVIAR = {"com.whatsapp:id/send", "com.whatsapp.w4b:id/send"};
    private final Handler principal = new Handler(Looper.getMainLooper());
    private volatile long ultimaPregunta = 0;

    @Override
    public void onAccessibilityEvent(AccessibilityEvent e) {
        if (Orden.pendiente(false) != null) {
            intentarEnviar();
            return;
        }
        // Al ver WhatsApp, pregunta al agente (como mucho una vez por segundo) si hay algo confirmado
        long ahora = System.currentTimeMillis();
        if (ahora - ultimaPregunta < 1000 || !Orden.configurada(this)) return;
        ultimaPregunta = ahora;
        new Thread(() -> {
            if (Agente.pedirOrden(this)) principal.post(this::intentarEnviar);
        }).start();
    }

    private void intentarEnviar() {
        String esperado = Orden.pendiente(false);
        if (esperado == null) return;
        AccessibilityNodeInfo raiz = getRootInActiveWindow();
        if (raiz == null) return;
        AccessibilityNodeInfo campo = buscar(raiz, CAMPOS);
        if (campo == null || campo.getText() == null) return;
        if (!normalizar(campo.getText().toString()).equals(normalizar(esperado))) return;
        AccessibilityNodeInfo boton = buscar(raiz, ENVIAR);
        if (boton == null) return;
        long marca = Orden.marca();
        if (Orden.pendiente(true) == null) return;  // consumir la orden: un solo envío
        boolean ok = boton.performAction(AccessibilityNodeInfo.ACTION_CLICK);
        // "enviado <marca>": el agente de JARVIS lo necesita para decir que esta orden concreta se envió
        Orden.registrar(this, (ok ? "enviado " : "fallo_pulsar ") + marca);
        Aviso.enviar(this, ok ? "enviado" : "fallo_pulsar", marca);
    }

    private static AccessibilityNodeInfo buscar(AccessibilityNodeInfo raiz, String[] ids) {
        for (String id : ids) {
            List<AccessibilityNodeInfo> nodos = raiz.findAccessibilityNodeInfosByViewId(id);
            if (nodos != null && !nodos.isEmpty()) return nodos.get(0);
        }
        return null;
    }

    private static String normalizar(String s) {
        return s.replace(' ', ' ').trim();
    }

    @Override
    public void onInterrupt() {}
}
