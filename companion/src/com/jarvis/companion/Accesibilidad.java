package com.jarvis.companion;

import android.accessibilityservice.AccessibilityService;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import org.json.JSONObject;

import java.net.URLEncoder;
import java.util.List;

/**
 * El corazón de la app. Mientras el permiso de accesibilidad está activado:
 *  1. Mantiene la conexión con JARVIS en el PC (pregunta en bucle si hay trabajo).
 *  2. Cuando llega un WhatsApp YA confirmado por el dueño, abre el chat con el texto escrito,
 *     pulsa "Enviar" solo si el texto escrito es exactamente el de la orden, y comprueba que se envió.
 *  3. Informa al PC del resultado y de cualquier error.
 * No lee ni guarda los chats.
 */
public class Accesibilidad extends AccessibilityService {
    static volatile boolean activa = false;
    private static final String[] CAMPOS = {"com.whatsapp:id/entry", "com.whatsapp.w4b:id/entry"};
    private static final String[] ENVIAR = {"com.whatsapp:id/send", "com.whatsapp.w4b:id/send"};

    private final Handler principal = new Handler(Looper.getMainLooper());
    private volatile boolean funcionando = false;
    // Trabajo en curso (un solo WhatsApp cada vez)
    private volatile long trabajoId = -1;
    private volatile String textoEsperado = null;
    private volatile long caduca = 0;
    private volatile boolean pulsado = false;

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        activa = true;
        funcionando = true;
        try {  // ver también los diálogos de WhatsApp (son ventanas aparte)
            android.accessibilityservice.AccessibilityServiceInfo info = getServiceInfo();
            info.flags |= android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
                    | android.accessibilityservice.AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS;
            info.packageNames = null;  // las "manos" trabajan en cualquier app, no solo en WhatsApp
            setServiceInfo(info);
        } catch (Exception ignored) {
        }
        // Si algo revienta, se guarda el motivo y se cuenta al PC en cuanto haya conexión
        final Thread.UncaughtExceptionHandler anterior = Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler((hilo, t) -> {
            java.io.StringWriter sw = new java.io.StringWriter();
            t.printStackTrace(new java.io.PrintWriter(sw));
            Conexion.prefs(this).edit().putString("fallo_pendiente", "la app se cerró por un fallo: "
                    + sw.toString().substring(0, Math.min(1500, sw.toString().length()))).commit();
            if (anterior != null) anterior.uncaughtException(hilo, t);
        });
        if (Palmadas.activadas(this) && !Palmadas.corriendo) {  // tras reiniciar el móvil, vuelven las palmadas
            try {
                startForegroundService(new Intent(this, Palmadas.class));
            } catch (Exception e) {
                Conexion.prefs(this).edit().putString("fallo_pendiente",
                        "no pude reactivar las palmadas al encender (ábreme y vuelve a activarlas): " + e.getMessage()).apply();
            }
        }
        new Thread(() -> {
            // El bucle de conexión nunca debe morir: si falla, se apunta y vuelve a empezar
            while (funcionando) {
                try {
                    bucle();
                } catch (Throwable t) {
                    Conexion.prefs(this).edit().putString("fallo_pendiente", "fallo en la conexión: " + t).apply();
                    dormir(3_000);
                }
            }
        }, "jarvis-conexion").start();
    }

    /** Cuenta al PC lo que pasó mientras estaba sin conexión (errores, cierres) para poder explicarlo. */
    private void contarPendientes(String desconexion) {
        String fallo = Conexion.prefs(this).getString("fallo_pendiente", null);
        if (fallo != null) {
            Conexion.prefs(this).edit().remove("fallo_pendiente").apply();
            Conexion.error(this, fallo);
        }
        if (desconexion != null) Conexion.error(this, desconexion);
        Escuchar.descargarSaludos(this);  // los saludos con su voz, listos para las palmadas o el botón
        try {
            Conexion.post(this, "/app/hola", new JSONObject().put("evento", "servicio escuchando a JARVIS"), 8000);
        } catch (Exception ignored) {
        }
    }

    @Override
    public void onDestroy() {
        funcionando = false;
        activa = false;
        super.onDestroy();
    }

    /** Pregunta al PC si hay trabajo. La petición se queda abierta hasta 25 s (casi no gasta batería). */
    private void bucle() {
        int fallos = 0;
        String sinConexionDesde = null;
        boolean primera = true;
        while (funcionando) {
            JSONObject pide = new JSONObject();
            try {
                pide.put("acuse", true);  // esta versión confirma cada encargo que recibe
            } catch (Exception ignored) {
            }
            Object[] r = Conexion.post(this, "/app/espera", pide, 35_000);
            int codigo = (int) r[0];
            if ((codigo == 200 || codigo == 204) && (primera || sinConexionDesde != null)) {
                final String motivo = sinConexionDesde;
                primera = false;
                sinConexionDesde = null;
                new Thread(() -> contarPendientes(motivo)).start();
            }
            if (codigo == 200) {
                fallos = 0;
                Conexion.anotar(this, "ultimo_contacto", "conectada con el PC");
                try {
                    JSONObject t = new JSONObject((String) r[1]);
                    long id = t.getLong("id");
                    // Acuse de recibo: si no llega, el PC lo reentrega (por si la entrega se perdió por el camino)
                    Conexion.post(this, "/app/resultado", new JSONObject().put("id", id).put("estado", "recibido"), 10_000);
                    String tipo = t.getString("tipo");
                    boolean nuevo = !yaVisto(id);  // UNA sola comprobación (marca el encargo como visto)
                    if (nuevo) Escuchar.apartar();  // JARVIS va a usar el móvil: la pantalla de «Hablar» se aparta
                    if (!nuevo) {
                        paso(id, "encargo repetido: ya lo tenía, no lo hago dos veces");
                    } else if ("whatsapp".equals(tipo)) {
                        JSONObject d = t.getJSONObject("datos");
                        paso(id, "recibido; abriendo WhatsApp");
                        principal.post(() -> empezarWhatsapp(id, d.optString("numero"), d.optString("texto"), null));
                    } else if ("whatsapp_audio".equals(tipo)) {
                        JSONObject d = t.getJSONObject("datos");
                        paso(id, "recibido; descargando el audio");
                        Uri audio;
                        try {
                            audio = bajarAudio(id, d.getString("sha256"));
                        } catch (Exception e) {
                            terminar(id, "error", "no pude preparar el audio: " + e.getMessage());
                            continue;
                        }
                        paso(id, "audio listo y comprobado; abriendo WhatsApp");
                        final boolean nota = "nota".equals(d.optString("modo", "archivo"));
                        principal.post(() -> {
                            notaDeVoz = nota;
                            empezarWhatsapp(id, d.optString("numero"), null, audio);
                        });
                    } else if ("movil_paso".equals(tipo)) {
                        JSONObject accion = t.getJSONObject("datos").getJSONObject("accion");
                        principal.post(() -> pasoDeManos(id, accion));
                    } else if ("leer_chat".equals(tipo)) {
                        JSONObject d = t.getJSONObject("datos");
                        paso(id, "abriendo el chat para leerlo");
                        principal.post(() -> leerChat(id, d.optString("numero")));
                    } else {
                        terminar(id, "error", "esta versión de la app no sabe hacer «" + tipo + "»");
                    }
                } catch (Exception e) {
                    Conexion.error(this, "trabajo ilegible: " + e.getMessage());
                }
            } else if (codigo == 204) {
                fallos = 0;
                Conexion.anotar(this, "ultimo_contacto", "conectada con el PC");
            } else {
                fallos++;
                String motivo = codigo == -1 ? (String) r[1] : "el PC respondió " + codigo;
                if (sinConexionDesde == null) {
                    sinConexionDesde = "estuvo sin conexión con el PC desde las "
                            + new java.text.SimpleDateFormat("HH:mm:ss").format(new java.util.Date()) + " (" + motivo + ")";
                }
                Conexion.anotar(this, "ultimo_error", "sin conexión con el PC: " + motivo);
                if (fallos == 3 && codigo != -1) Conexion.error(this, "sin conexión con el PC: " + motivo);
                dormir(Math.min(30_000, 2_000L * fallos));
            }
        }
    }

    // Los últimos encargos ya hechos: un encargo reentregado nunca se manda dos veces
    private final java.util.ArrayDeque<Long> vistos = new java.util.ArrayDeque<>();

    private synchronized boolean yaVisto(long id) {
        if (vistos.contains(id)) return true;
        vistos.addLast(id);
        if (vistos.size() > 50) vistos.removeFirst();
        return false;
    }

    /** Cuenta al PC por dónde va (así, si algo falla, se sabe exactamente dónde). */
    private void paso(long id, String texto) {
        new Thread(() -> {
            try {
                Conexion.post(this, "/app/hola", new JSONObject().put("id", id).put("paso", texto), 8000);
            } catch (Exception ignored) {
            }
        }).start();
    }

    private volatile boolean vioWhatsapp = false;
    private volatile boolean modoAudio = false;
    private volatile long inicio = 0;

    /**
     * WhatsApp Business manda el audio compartido a un chat SIN preguntar y vuelve a la lista de chats.
     * Se da por enviado solo si en esa lista aparece un audio o nota de voz con la hora de ahora (o la de inicio).
     * Devuelve cómo lo muestra WhatsApp ("Audio", "Mensaje de voz (0:04)"…) o null.
     */
    private String audioYaEnviado() {
        java.text.SimpleDateFormat hm = new java.text.SimpleDateFormat("HH:mm");
        java.util.Set<String> horas = new java.util.HashSet<>();
        horas.add(hm.format(new java.util.Date(inicio)));
        horas.add(hm.format(new java.util.Date()));
        for (AccessibilityNodeInfo r : raicesWhatsapp()) {
            for (String sufijo : new String[]{":id/single_msg_tv", ":id/conversations_row_message_view"}) {
                for (String pq : new String[]{"com.whatsapp.w4b", "com.whatsapp"}) {
                    List<AccessibilityNodeInfo> msgs = r.findAccessibilityNodeInfosByViewId(pq + sufijo);
                    if (msgs == null) continue;
                    for (AccessibilityNodeInfo m : msgs) {
                        String t = m.getText() == null ? "" : m.getText().toString().trim();
                        if (!t.matches("(?i)^(audio|mensaje de voz|nota de voz|voice message).*")) continue;
                        // Subir hasta la fila del chat y mirar su hora
                        AccessibilityNodeInfo fila = m;
                        for (int i = 0; i < 6 && fila != null; i++) {
                            List<AccessibilityNodeInfo> fechas = fila.findAccessibilityNodeInfosByViewId(pq + ":id/conversations_row_date");
                            if (fechas != null && !fechas.isEmpty()) {
                                CharSequence f = fechas.get(0).getText();
                                if (f != null && horas.contains(f.toString().trim())) return t;
                                break;
                            }
                            fila = fila.getParent();
                        }
                    }
                }
            }
        }
        return null;
    }

    /** Descarga el audio del PC, comprueba su huella SHA-256 (que llegó entero y es el confirmado) y lo guarda. */
    private Uri bajarAudio(long id, String huella) throws Exception {
        byte[] datos = Conexion.descargar(this, "/app/audio", new JSONObject().put("sha256", huella), 30_000);
        java.security.MessageDigest md = java.security.MessageDigest.getInstance("SHA-256");
        StringBuilder hex = new StringBuilder();
        for (byte b : md.digest(datos)) hex.append(String.format("%02x", b));
        if (!hex.toString().equals(huella)) throw new Exception("el audio llegó dañado");
        if (android.os.Build.VERSION.SDK_INT < 29) throw new Exception("hace falta Android 10 o más");
        android.content.ContentValues v = new android.content.ContentValues();
        // Nombre como el de las notas de voz de WhatsApp (PTT-fecha-WAnnnn.opus): así puede tratarlo como nota de voz
        String fecha = new java.text.SimpleDateFormat("yyyyMMdd").format(new java.util.Date());
        v.put(android.provider.MediaStore.MediaColumns.DISPLAY_NAME,
                "PTT-" + fecha + "-WA" + String.format(java.util.Locale.ROOT, "%04d", id % 10000) + ".opus");
        v.put(android.provider.MediaStore.MediaColumns.MIME_TYPE, "audio/ogg");
        v.put(android.provider.MediaStore.MediaColumns.RELATIVE_PATH, "Music/JARVIS");
        v.put(android.provider.MediaStore.MediaColumns.IS_PENDING, 1);
        Uri uri = getContentResolver().insert(android.provider.MediaStore.Audio.Media.EXTERNAL_CONTENT_URI, v);
        if (uri == null) throw new Exception("no pude guardar el audio en el móvil");
        try (java.io.OutputStream os = getContentResolver().openOutputStream(uri)) {
            os.write(datos);
        }
        v.clear();
        v.put(android.provider.MediaStore.MediaColumns.IS_PENDING, 0);
        getContentResolver().update(uri, v, null, null);
        // Se borra del móvil a los 10 minutos (WhatsApp ya tiene su copia)
        principal.postDelayed(() -> {
            try {
                getContentResolver().delete(uri, null, null);
            } catch (Exception ignored) {
            }
        }, 600_000);
        return uri;
    }

    private void empezarWhatsapp(long id, String numero, String texto, Uri audio) {
        if (numero == null || numero.isEmpty() || (audio == null && (texto == null || texto.isEmpty()))) {
            terminar(id, "error", "orden sin número o sin texto");
            return;
        }
        // Con el móvil bloqueado (PIN/huella) WhatsApp se abriría DETRÁS de la pantalla de bloqueo y no se
        // podría pulsar Enviar. Se espera a que el dueño desbloquee (máx. 3 min); JARVIS le avisa por Telegram.
        android.app.KeyguardManager km = (android.app.KeyguardManager) getSystemService(KEYGUARD_SERVICE);
        if (km != null && km.isKeyguardLocked()) {
            paso(id, "esperando desbloqueo del móvil");
            final boolean[] hecho = {false};
            final android.content.BroadcastReceiver alDesbloquear = new android.content.BroadcastReceiver() {
                @Override
                public void onReceive(android.content.Context c, Intent in) {
                    if (hecho[0]) return;
                    hecho[0] = true;
                    try {
                        unregisterReceiver(this);
                    } catch (Exception ignored) {
                    }
                    paso(id, "móvil desbloqueado");
                    principal.postDelayed(() -> empezarWhatsapp(id, numero, texto, audio), 600);
                }
            };
            android.content.IntentFilter filtro = new android.content.IntentFilter(Intent.ACTION_USER_PRESENT);
            if (android.os.Build.VERSION.SDK_INT >= 33) {
                registerReceiver(alDesbloquear, filtro, RECEIVER_NOT_EXPORTED);
            } else {
                registerReceiver(alDesbloquear, filtro);
            }
            principal.postDelayed(() -> {
                if (hecho[0]) return;
                hecho[0] = true;
                try {
                    unregisterReceiver(alDesbloquear);
                } catch (Exception ignored) {
                }
                terminar(id, "error", "el móvil siguió bloqueado 3 minutos, así que no se envió");
            }, 180_000);
            return;
        }
        trabajoId = id;
        modoAudio = audio != null;
        inicio = System.currentTimeMillis();
        textoEsperado = audio != null ? "" : texto;
        caduca = System.currentTimeMillis() + 30_000;
        pulsado = false;
        vioWhatsapp = false;
        audioActual = audio;
        numeroActual = numero;
        if (audio != null && notaDeVoz) {
            try {  // se prepara ya el reproductor para saber cuánto dura (y cuánto hay que mantener el micrófono)
                prepararReproductor(audio);
                caduca = System.currentTimeMillis() + 30_000 + reproductor.getDuration();
            } catch (Exception e) {
                paso(id, "no pude preparar la nota de voz (" + e.getMessage() + "); lo mando como Audio");
                notaDeVoz = false;
            }
        }
        try {
            Intent i;
            String digitos = numero.replaceAll("[^0-9]", "");
            if (audio != null && notaDeVoz) {
                // Nota de voz: se abre el chat vacío; luego se graba manteniendo pulsado el micrófono
                i = new Intent(Intent.ACTION_VIEW, Uri.parse("https://wa.me/" + digitos));
            } else if (audio != null) {
                // El audio se comparte directamente al chat de esa persona ("jid" = número@s.whatsapp.net)
                i = new Intent(Intent.ACTION_SEND);
                i.setType("audio/ogg");
                i.putExtra(Intent.EXTRA_STREAM, audio);
                i.putExtra("jid", digitos + "@s.whatsapp.net");
                i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            } else {
                String url = "https://wa.me/" + digitos + "?text=" + URLEncoder.encode(texto, "UTF-8").replace("+", "%20");
                i = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
            }
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
            // WhatsApp normal y, si no, WhatsApp Business. Se intenta abrir de verdad (no basta con "verlo").
            String paquete = instalado("com.whatsapp.w4b") && !instalado("com.whatsapp") ? "com.whatsapp.w4b" : "com.whatsapp";
            i.setPackage(paquete);
            try {
                startActivity(i);
            } catch (android.content.ActivityNotFoundException sinApp) {
                i.setPackage(paquete.equals("com.whatsapp") ? "com.whatsapp.w4b" : "com.whatsapp");
                try {
                    startActivity(i);
                } catch (android.content.ActivityNotFoundException tampoco) {
                    terminar(id, "error", "WhatsApp no está instalado (no se pudo abrir ni WhatsApp ni WhatsApp Business)");
                    return;
                }
            }
            paso(id, "pedí abrir el chat en " + i.getPackage());
        } catch (Exception e) {
            terminar(id, "error", "no pude abrir WhatsApp: " + e.getMessage());
            return;
        }
        final int mio = ++intento;  // si se reintenta de otra forma, los relojes del intento anterior no cuentan
        // No solo se espera a los avisos de WhatsApp: se revisa la pantalla cada 0,7 s por si acaso
        final Runnable revisarCada = new Runnable() {
            @Override
            public void run() {
                if (trabajoId != id || intento != mio || pulsado || System.currentTimeMillis() > caduca) return;
                revisar();
                principal.postDelayed(this, 700);
            }
        };
        principal.postDelayed(revisarCada, 700);
        // A los 12 s sin éxito, se le cuenta al PC qué hay en pantalla; si era una nota de voz, se manda como Audio
        principal.postDelayed(() -> {
            if (trabajoId != id || intento != mio || pulsado) return;
            if (modoAudio && notaDeVoz) {
                pasarAArchivo(id, "no encontré el micrófono de WhatsApp. En pantalla: " + volcado());
            } else {
                paso(id, "aún no veo el botón; en pantalla: " + volcado());
            }
        }, 12_000);
        // Si en 30 s no se ha podido pulsar Enviar, se dice el motivo (nunca se da por enviado)
        principal.postDelayed(() -> {
            if (trabajoId == id && intento == mio && !pulsado) terminar(id, "error", diagnostico());
        }, 30_000);
    }

    // --- Las manos: una acción en cualquier app y la pantalla que queda después -----------------------------

    private void pasoDeManos(long id, JSONObject accion) {
        final String hecho;
        try {
            hecho = Manos.hacer(this, accion);
        } catch (Exception e) {
            terminar(id, "error", e.getMessage() == null ? e.toString() : e.getMessage());
            return;
        }
        boolean soloVer = "ver".equals(accion.optString("tipo", "ver"));
        principal.postDelayed(() -> {
            try {
                JSONObject p = Manos.ver(this);
                p.put("hecho", hecho);
                terminar(id, "pantalla", p.toString());
            } catch (Exception e) {
                terminar(id, "error", "hecho (" + hecho + "), pero no pude ver la pantalla: " + e.getMessage());
            }
        }, soloVer ? 50 : 900);
    }

    // --- Leer un chat (para que JARVIS pueda responder con coherencia) --------------------------------------
    // Solo LEE: no escribe ni pulsa nada. Lo leído va al PC para esa petición (no se guarda en la app).

    private void leerChat(long id, String numero) {
        android.app.KeyguardManager km = (android.app.KeyguardManager) getSystemService(KEYGUARD_SERVICE);
        if (km != null && km.isKeyguardLocked()) {
            terminar(id, "error", "el móvil está bloqueado: desbloquéalo y vuelve a pedírmelo");
            return;
        }
        String digitos = numero == null ? "" : numero.replaceAll("[^0-9]", "");
        if (digitos.isEmpty()) {
            terminar(id, "error", "falta el número del chat");
            return;
        }
        Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse("https://wa.me/" + digitos));
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        i.setPackage(instalado("com.whatsapp.w4b") && !instalado("com.whatsapp") ? "com.whatsapp.w4b" : "com.whatsapp");
        try {
            startActivity(i);
        } catch (Exception e) {
            terminar(id, "error", "no pude abrir el chat: " + e.getMessage());
            return;
        }
        esperarChatYLeer(id, System.currentTimeMillis() + 15_000);
    }

    private void esperarChatYLeer(long id, long hasta) {
        boolean abierto = false;
        for (AccessibilityNodeInfo r : raicesWhatsapp()) {
            AccessibilityNodeInfo c = buscar(r, CAMPOS);
            if (c != null && c.isVisibleToUser()) abierto = true;
        }
        if (!abierto) {
            if (System.currentTimeMillis() > hasta) {
                terminar(id, "error", "el chat no llegó a abrirse");
            } else {
                principal.postDelayed(() -> esperarChatYLeer(id, hasta), 600);
            }
            return;
        }
        final List<String[]> recientes = mensajesEnPantalla();
        // Un poco hacia arriba, para tener más contexto
        AccessibilityNodeInfo lista = listaDesplazable();
        if (lista != null) lista.performAction(AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD);
        principal.postDelayed(() -> {
            List<String[]> anteriores = mensajesEnPantalla();
            AccessibilityNodeInfo l2 = listaDesplazable();
            if (l2 != null) l2.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD);
            java.util.LinkedHashMap<String, String[]> todos = new java.util.LinkedHashMap<>();
            for (String[] m : anteriores) todos.put(m[0] + "|" + m[1] + "|" + m[2], m);
            for (String[] m : recientes) todos.put(m[0] + "|" + m[1] + "|" + m[2], m);
            org.json.JSONArray arr = new org.json.JSONArray();
            List<String[]> lista2 = new java.util.ArrayList<>(todos.values());
            for (String[] m : lista2.subList(Math.max(0, lista2.size() - 20), lista2.size())) {
                try {
                    arr.put(new JSONObject().put("de", m[0]).put("texto", m[1]).put("hora", m[2]));
                } catch (Exception ignored) {
                }
            }
            terminar(id, "leido", arr.toString());
        }, 900);
    }

    private AccessibilityNodeInfo listaDesplazable() {
        for (AccessibilityNodeInfo r : raicesWhatsapp()) {
            java.util.ArrayDeque<AccessibilityNodeInfo> cola = new java.util.ArrayDeque<>();
            cola.add(r);
            while (!cola.isEmpty()) {
                AccessibilityNodeInfo x = cola.poll();
                if (x == null) continue;
                if (x.isScrollable()) return x;
                for (int k = 0; k < x.getChildCount(); k++) cola.add(x.getChild(k));
            }
        }
        return null;
    }

    /** Los mensajes visibles del chat, de arriba a abajo: {de ("yo" / "el_otro"), texto, hora}. */
    private List<String[]> mensajesEnPantalla() {
        List<String[]> res = new java.util.ArrayList<>();
        int ancho = getResources().getDisplayMetrics().widthPixels;
        android.graphics.Rect b = new android.graphics.Rect();
        for (AccessibilityNodeInfo r : raicesWhatsapp()) {
            java.util.ArrayDeque<AccessibilityNodeInfo> cola = new java.util.ArrayDeque<>();
            cola.add(r);
            while (!cola.isEmpty()) {
                AccessibilityNodeInfo x = cola.poll();
                if (x == null) continue;
                String vid = x.getViewIdResourceName() == null ? "" : x.getViewIdResourceName();
                CharSequence desc = x.getContentDescription();
                if (vid.endsWith(":id/message_text") && x.getText() != null) {
                    x.getBoundsInScreen(b);
                    // Los mensajes recibidos van pegados a la izquierda; los míos, a la derecha
                    String de = b.left < ancho * 0.1 ? "el_otro" : "yo";
                    String texto = x.getText().toString();
                    res.add(new String[]{de, texto.length() > 400 ? texto.substring(0, 400) : texto, horaDe(x)});
                } else if (vid.endsWith(":id/main_layout") && desc != null
                        && desc.toString().matches("(?i).*mensaje de (voz|audio).*")) {
                    String d = desc.toString();
                    String de = d.startsWith("Tú") ? "yo" : "el_otro";
                    java.util.regex.Matcher m = java.util.regex.Pattern.compile("(\\d{1,2}:\\d{2})").matcher(d);
                    String hora = "";
                    while (m.find()) hora = m.group(1);
                    res.add(new String[]{de, "[nota de voz]", hora});
                }
                for (int k = 0; k < x.getChildCount(); k++) cola.add(x.getChild(k));
            }
        }
        return res;
    }

    /** La hora del globo del mensaje (el nodo "date" que va con él). */
    private static String horaDe(AccessibilityNodeInfo n) {
        AccessibilityNodeInfo p = n.getParent();
        for (int i = 0; i < 3 && p != null; i++, p = p.getParent()) {
            for (String pq : new String[]{"com.whatsapp.w4b", "com.whatsapp"}) {
                List<AccessibilityNodeInfo> f = p.findAccessibilityNodeInfosByViewId(pq + ":id/date");
                if (f != null && !f.isEmpty() && f.get(0).getText() != null) return f.get(0).getText().toString();
            }
        }
        return "";
    }

    // --- Nota de voz de verdad: mantener pulsado el micrófono de WhatsApp mientras suena el audio -------------

    private volatile boolean notaDeVoz = false;
    private volatile int intento = 0;
    private volatile Uri audioActual = null;
    private volatile String numeroActual = null;
    private android.media.MediaPlayer reproductor;
    private static final String[] MICRO = {"com.whatsapp:id/voice_note_btn", "com.whatsapp.w4b:id/voice_note_btn"};

    private void prepararReproductor(Uri u) throws Exception {
        soltarReproductor();
        reproductor = new android.media.MediaPlayer();
        // Por el canal de accesibilidad: así Android no lo silencia cuando WhatsApp empieza a grabar
        reproductor.setAudioAttributes(new android.media.AudioAttributes.Builder()
                .setUsage(android.media.AudioAttributes.USAGE_ASSISTANCE_ACCESSIBILITY)
                .setContentType(android.media.AudioAttributes.CONTENT_TYPE_SPEECH).build());
        reproductor.setDataSource(this, u);
        reproductor.prepare();
    }

    private void soltarReproductor() {
        if (reproductor != null) {
            try {
                reproductor.release();
            } catch (Exception ignored) {
            }
            reproductor = null;
        }
    }

    /** Si la nota de voz no se puede grabar, se manda el mismo audio como «Audio» (y se dice por qué). */
    private void pasarAArchivo(long id, String motivo) {
        teclado();
        paso(id, "nota de voz imposible: " + motivo + " → lo mando como Audio");
        soltarReproductor();
        notaDeVoz = false;
        textoEsperado = null;
        trabajoId = -1;
        empezarWhatsapp(id, numeroActual, null, audioActual);
    }

    private AccessibilityNodeInfo microfono() {
        for (AccessibilityNodeInfo r : raicesWhatsapp()) {
            // Solo dentro de un chat abierto (con su caja de texto VACÍA): nunca en la lista de chats
            AccessibilityNodeInfo campo = buscar(r, CAMPOS);
            if (campo == null || !campo.isVisibleToUser()) continue;
            if (campo.getText() != null && campo.getText().toString().trim().length() > 0
                    && !campo.getText().toString().matches("(?i)^(mensaje|message|escribe).*")) continue;
            AccessibilityNodeInfo m = buscar(r, MICRO);
            if (m != null && m.isVisibleToUser()) return m;
            java.util.ArrayDeque<AccessibilityNodeInfo> cola = new java.util.ArrayDeque<>();
            cola.add(r);
            while (!cola.isEmpty()) {
                AccessibilityNodeInfo x = cola.poll();
                if (x == null) continue;
                CharSequence d = x.getContentDescription();
                String vid = x.getViewIdResourceName() == null ? "" : x.getViewIdResourceName();
                if (d != null && x.isVisibleToUser() && (vid.isEmpty() || vid.contains("voice"))
                        && d.toString().length() < 40
                        && d.toString().matches("(?i).*(mensaje de voz|nota de voz|grabar audio|voice message|record voice).*")) {
                    return x;
                }
                for (int i = 0; i < x.getChildCount(); i++) cola.add(x.getChild(i));
            }
        }
        return null;
    }

    /** Pulsa el micrófono solo cuando lleva quieto 0,7 s en el mismo sitio (el teclado ya no lo mueve). */
    private void esperarQuieto(long id, android.graphics.Rect antes, int vueltas) {
        if (trabajoId != id) return;
        AccessibilityNodeInfo mic = microfono();
        if (mic == null) {
            teclado();
            pasarAArchivo(id, "el micrófono desapareció de la pantalla");
            return;
        }
        android.graphics.Rect ahora = new android.graphics.Rect();
        mic.getBoundsInScreen(ahora);
        if (!ahora.equals(antes) && vueltas < 6) {
            principal.postDelayed(() -> esperarQuieto(id, ahora, vueltas + 1), 700);
            return;
        }
        String vid = mic.getViewIdResourceName() == null ? "" : mic.getViewIdResourceName().replaceAll("^.*:id/", "");
        paso(id, "micrófono quieto en " + ahora.toShortString() + " [" + vid + "|" + mic.getContentDescription() + "]");
        grabarNota(id, mic);
    }

    /** Devuelve el teclado a su modo normal. */
    private void teclado() {
        try {
            getSoftKeyboardController().setShowMode(SHOW_MODE_AUTO);
        } catch (Exception ignored) {
        }
    }

    private void grabarNota(long id, AccessibilityNodeInfo mic) {
        android.graphics.Rect r = new android.graphics.Rect();
        mic.getBoundsInScreen(r);
        int dura = reproductor == null ? 0 : reproductor.getDuration();
        long total = 1000 + dura + 900;  // un poco de silencio antes y después
        if (reproductor == null || total > android.accessibilityservice.GestureDescription.getMaxGestureDuration()) {
            pasarAArchivo(id, "el audio es demasiado largo para grabarlo como nota de voz");
            return;
        }
        final android.media.AudioManager am = (android.media.AudioManager) getSystemService(AUDIO_SERVICE);
        final int canal = android.media.AudioManager.STREAM_ACCESSIBILITY;
        final int antes = am.getStreamVolume(canal);
        try {
            am.setStreamVolume(canal, am.getStreamMaxVolume(canal), 0);
        } catch (Exception ignored) {
        }
        android.graphics.Path p = new android.graphics.Path();
        p.moveTo(r.exactCenterX(), r.exactCenterY());
        android.accessibilityservice.GestureDescription g = new android.accessibilityservice.GestureDescription.Builder()
                .addStroke(new android.accessibilityservice.GestureDescription.StrokeDescription(p, 0, total)).build();
        paso(id, "grabando la nota de voz (" + Math.round(dura / 1000.0) + " s)");
        boolean ok = dispatchGesture(g, new GestureResultCallback() {
            @Override
            public void onCompleted(android.accessibilityservice.GestureDescription gd) {
                restaurar(am, canal, antes);
                principal.postDelayed(() -> comprobarNota(id), 2500);
            }

            @Override
            public void onCancelled(android.accessibilityservice.GestureDescription gd) {
                restaurar(am, canal, antes);
                terminar(id, "error", "se interrumpió la grabación de la nota de voz (¿se tocó la pantalla?); "
                        + "puede que WhatsApp no la enviara: mira el chat");
            }
        }, principal);
        if (!ok) {
            restaurar(am, canal, antes);
            pasarAArchivo(id, "Android no me dejó mantener pulsado el micrófono");
            return;
        }
        principal.postDelayed(() -> {
            // ¿Está grabando? (lo que se ve en pantalla se manda al PC para poder comprobarlo)
            paso(id, "mientras grabo, abajo: " + volcadoAbajo());
            try {
                reproductor.start();
            } catch (Exception e) {
                paso(id, "no pude reproducir el audio: " + e.getMessage());
            }
        }, 1000);
    }

    private void restaurar(android.media.AudioManager am, int canal, int antes) {
        try {
            am.setStreamVolume(canal, antes, 0);
        } catch (Exception ignored) {
        }
        soltarReproductor();
        teclado();
    }

    /** Tras soltar el micrófono, WhatsApp la envía. Se comprueba en la lista de chats que aparece como nota de voz. */
    private void comprobarNota(long id) {
        paso(id, "tras soltar, abajo: " + volcadoAbajo());
        performGlobalAction(GLOBAL_ACTION_BACK);
        principal.postDelayed(() -> {
            String como = audioYaEnviado();
            if (como != null) {
                terminar(id, "enviado", "Nota de voz enviada; en WhatsApp aparece como «" + como + "»");
            } else {
                terminar(id, "error", "grabé la nota de voz y solté el micrófono, pero no he podido comprobar que "
                        + "se enviara: mira el chat. En pantalla: " + volcado());
            }
        }, 1800);
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent e) {
        revisar();
    }

    /** Las ventanas de WhatsApp que hay en pantalla (la principal y los diálogos, que son ventanas aparte). */
    private List<AccessibilityNodeInfo> raicesWhatsapp() {
        List<AccessibilityNodeInfo> raices = new java.util.ArrayList<>();
        try {
            for (android.view.accessibility.AccessibilityWindowInfo w : getWindows()) {
                AccessibilityNodeInfo r = w.getRoot();
                if (r != null && String.valueOf(r.getPackageName()).startsWith("com.whatsapp")) raices.add(r);
            }
        } catch (Exception ignored) {
        }
        if (raices.isEmpty()) {
            AccessibilityNodeInfo r = getRootInActiveWindow();
            if (r != null && String.valueOf(r.getPackageName()).startsWith("com.whatsapp")) raices.add(r);
        }
        return raices;
    }

    private AccessibilityNodeInfo enviarAudioEnPantalla() {
        for (AccessibilityNodeInfo r : raicesWhatsapp()) {
            AccessibilityNodeInfo b = botonEnviarAudio(r);
            if (b != null) return b;
        }
        return null;
    }

    private synchronized void revisar() {
        if (textoEsperado == null || pulsado || System.currentTimeMillis() > caduca) return;
        if (modoAudio && notaDeVoz) {
            if (raicesWhatsapp().isEmpty()) return;
            if (!vioWhatsapp) {
                vioWhatsapp = true;
                paso(trabajoId, "chat de WhatsApp abierto");
            }
            AccessibilityNodeInfo mic = microfono();
            if (mic == null) return;
            pulsado = true;
            final long id = trabajoId;
            // El teclado puede estar saliendo y mover el micrófono: se esconde y se espera a que el botón esté quieto
            try {
                getSoftKeyboardController().setShowMode(SHOW_MODE_HIDDEN);
            } catch (Exception ignored) {
            }
            android.graphics.Rect antes = new android.graphics.Rect();
            mic.getBoundsInScreen(antes);
            principal.postDelayed(() -> esperarQuieto(id, antes, 0), 700);
            return;
        }
        if (modoAudio) {
            if (raicesWhatsapp().isEmpty()) return;
            if (!vioWhatsapp) {
                vioWhatsapp = true;
                paso(trabajoId, "WhatsApp abierto en pantalla");
            }
            AccessibilityNodeInfo enviar = enviarAudioEnPantalla();
            if (enviar == null) {
                // ¿WhatsApp ya lo mandó él solo? (lo hace al compartir a un chat concreto)
                String como = System.currentTimeMillis() - inicio > 1500 ? audioYaEnviado() : null;
                if (como != null) {
                    pulsado = true;
                    terminar(trabajoId, "enviado", "Audio enviado; en WhatsApp aparece como «" + como + "»");
                }
                return;
            }
            pulsado = true;
            final long id = trabajoId;
            paso(id, "pulso Enviar en la pantalla del audio");
            if (!pulsar(enviar)) {
                terminar(id, "error", "WhatsApp no dejó pulsar Enviar en el audio");
                return;
            }
            // Comprobación: tras pulsar, la pantalla/diálogo de envío tiene que desaparecer
            principal.postDelayed(() -> {
                if (enviarAudioEnPantalla() != null) {
                    terminar(id, "error", "pulsé Enviar pero la pantalla de envío del audio sigue abierta");
                } else {
                    terminar(id, "enviado", "Audio enviado");
                }
            }, 2500);
            return;
        }
        AccessibilityNodeInfo raiz = getRootInActiveWindow();
        if (raiz == null) return;
        if (!vioWhatsapp && String.valueOf(raiz.getPackageName()).startsWith("com.whatsapp")) {
            vioWhatsapp = true;
            paso(trabajoId, "WhatsApp abierto en pantalla");
        }
        AccessibilityNodeInfo campo = buscar(raiz, CAMPOS);
        if (campo == null || campo.getText() == null) return;
        if (!normalizar(campo.getText().toString()).equals(normalizar(textoEsperado))) return;
        AccessibilityNodeInfo boton = buscar(raiz, ENVIAR);
        if (boton == null) return;
        pulsado = true;
        final long id = trabajoId;
        if (!boton.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
            terminar(id, "error", "WhatsApp no dejó pulsar Enviar");
            return;
        }
        // Comprobación: tras pulsar, la caja de texto tiene que quedarse vacía
        principal.postDelayed(() -> {
            AccessibilityNodeInfo r2 = getRootInActiveWindow();
            AccessibilityNodeInfo c2 = r2 == null ? null : buscar(r2, CAMPOS);
            String queda = (c2 == null || c2.getText() == null) ? "" : normalizar(c2.getText().toString());
            if (queda.equals(normalizar(textoEsperado == null ? "" : textoEsperado))) {
                terminar(id, "error", "pulsé Enviar pero el mensaje sigue escrito");
            } else {
                terminar(id, "enviado", "WhatsApp enviado");
            }
        }, 1500);
    }

    /** El botón de enviar de la pantalla (o el diálogo) que WhatsApp muestra al compartirle un audio. */
    private static AccessibilityNodeInfo botonEnviarAudio(AccessibilityNodeInfo raiz) {
        if (!String.valueOf(raiz.getPackageName()).startsWith("com.whatsapp")) return null;
        // Seguridad: si es un chat con texto escrito, su botón Enviar mandaría ESE texto, no el audio
        AccessibilityNodeInfo campo = buscar(raiz, CAMPOS);
        boolean hayTextoEscrito = campo != null && campo.getText() != null && campo.getText().toString().trim().length() > 0
                && campo.isVisibleToUser();
        AccessibilityNodeInfo b = hayTextoEscrito ? null : buscar(raiz, ENVIAR);
        if (b != null && b.isVisibleToUser()) return b;
        b = buscar(raiz, new String[]{"android:id/button1", "com.whatsapp:id/send_btn", "com.whatsapp.w4b:id/send_btn"});
        if (b != null && b.isVisibleToUser()) return b;
        for (String t : new String[]{"Enviar", "ENVIAR", "Send", "SEND"}) {
            List<AccessibilityNodeInfo> nodos = raiz.findAccessibilityNodeInfosByText(t);
            if (nodos == null) continue;
            for (AccessibilityNodeInfo n : nodos) {
                CharSequence txt = n.getText() != null ? n.getText() : n.getContentDescription();
                if (txt != null && txt.toString().trim().equalsIgnoreCase(t) && n.isVisibleToUser()) return n;
            }
        }
        return null;
    }

    /** Pulsa el nodo o, si no es pulsable, el primer padre que lo sea. */
    private static boolean pulsar(AccessibilityNodeInfo n) {
        for (int i = 0; n != null && i < 4; i++, n = n.getParent()) {
            if (n.isClickable()) return n.performAction(AccessibilityNodeInfo.ACTION_CLICK);
        }
        return false;
    }

    /** Lo de la parte de abajo de la pantalla (donde están la caja de texto, el micrófono y el contador de grabación). */
    private String volcadoAbajo() {
        int alto = getResources().getDisplayMetrics().heightPixels;
        StringBuilder sb = new StringBuilder();
        java.util.ArrayDeque<AccessibilityNodeInfo> cola = new java.util.ArrayDeque<>(raicesWhatsapp());
        int n = 0;
        android.graphics.Rect b = new android.graphics.Rect();
        while (!cola.isEmpty() && n < 25) {
            AccessibilityNodeInfo x = cola.poll();
            if (x == null) continue;
            x.getBoundsInScreen(b);
            if (x.isVisibleToUser() && b.top > alto * 0.6
                    && (x.isClickable() || x.getText() != null || x.getContentDescription() != null)) {
                String id = x.getViewIdResourceName() == null ? "" : x.getViewIdResourceName().replaceAll("^.*:id/", "");
                sb.append("[").append(id).append("|").append(x.getText() == null ? "" : x.getText())
                  .append("|").append(x.getContentDescription() == null ? "" : x.getContentDescription())
                  .append("|").append(b.toShortString()).append("] ");
                n++;
            }
            for (int i = 0; i < x.getChildCount(); i++) cola.add(x.getChild(i));
        }
        return sb.length() == 0 ? "(nada abajo)" : sb.toString();
    }

    /** Lo que hay en las ventanas de WhatsApp: botones y textos visibles (id | texto | descripción). */
    private String volcado() {
        StringBuilder sb = new StringBuilder();
        java.util.ArrayDeque<AccessibilityNodeInfo> cola = new java.util.ArrayDeque<>(raicesWhatsapp());
        int n = 0;
        while (!cola.isEmpty() && n < 30) {
            AccessibilityNodeInfo x = cola.poll();
            if (x == null) continue;
            if (x.isVisibleToUser() && (x.isClickable() || x.getText() != null || x.getContentDescription() != null)) {
                String id = x.getViewIdResourceName() == null ? "" : x.getViewIdResourceName().replaceAll("^.*:id/", "");
                String txt = x.getText() == null ? "" : x.getText().toString();
                String desc = x.getContentDescription() == null ? "" : x.getContentDescription().toString();
                if (!txt.isEmpty() || !desc.isEmpty() || x.isClickable()) {
                    sb.append("[").append(id).append("|").append(txt.length() > 25 ? txt.substring(0, 25) : txt)
                      .append("|").append(desc).append(x.isClickable() ? "|pulsable" : "").append("] ");
                    n++;
                }
            }
            for (int i = 0; i < x.getChildCount(); i++) cola.add(x.getChild(i));
        }
        return sb.length() == 0 ? "(nada visible)" : sb.toString();
    }

    private String diagnostico() {
        if (modoAudio && !raicesWhatsapp().isEmpty()) {
            return "WhatsApp se abrió pero no encontré el botón de enviar el audio. En pantalla: " + volcado();
        }
        AccessibilityNodeInfo raiz = getRootInActiveWindow();
        if (raiz == null) return "no se abrió WhatsApp (o no puedo ver la pantalla)";
        String paquete = String.valueOf(raiz.getPackageName());
        if (!paquete.startsWith("com.whatsapp")) return "WhatsApp no llegó a abrirse (pantalla actual: " + paquete + ")";
        AccessibilityNodeInfo campo = buscar(raiz, CAMPOS);
        if (campo == null) return "WhatsApp se abrió pero no encontré la caja de texto del chat";
        return "el texto escrito en el chat no coincide con el confirmado, así que no lo envié";
    }

    private void terminar(long id, String estado, String detalle) {
        if (trabajoId == id) {
            textoEsperado = null;
            modoAudio = false;
            trabajoId = -1;
        }
        // Lo leído de un chat no se apunta en la app (privacidad): solo que se leyó
        // Lo que se ve en pantalla o se lee de un chat no se apunta en la app (privacidad)
        if (!"pantalla".equals(estado)) {
            Conexion.anotar(this, "ultimo_envio", "leido".equals(estado) ? "leído un chat para JARVIS" : estado + ": " + detalle);
        }
        new Thread(() -> {
            for (int intento = 0; intento < 4; intento++) {  // el resultado tiene que llegar al PC
                try {
                    Object[] r = Conexion.post(this, "/app/resultado",
                            new JSONObject().put("id", id).put("estado", estado).put("detalle", detalle), 10_000);
                    if ((int) r[0] == 200) return;
                } catch (Exception ignored) {
                }
                dormir(2_000);
            }
        }).start();
    }

    private boolean instalado(String paquete) {
        try {
            getPackageManager().getPackageInfo(paquete, 0);
            return true;
        } catch (PackageManager.NameNotFoundException e) {
            return false;
        }
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

    private static void dormir(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException ignored) {
        }
    }

    @Override
    public void onInterrupt() {}
}
