package com.jarvis.companion;

import android.content.Context;
import android.graphics.BlurMaskFilter;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.view.View;

/**
 * El "reactor" de JARVIS: anillos que giran y laten. Cambia según lo que hace:
 * ESCUCHANDO (late con tu voz), PENSANDO (gira deprisa), HABLANDO (vibra), EN ESPERA (gira despacio).
 */
public class Reactor extends View {
    static final int ESPERA = 0, ESCUCHANDO = 1, PENSANDO = 2, HABLANDO = 3;
    private static final int CIAN = Color.parseColor("#4FD8FF");
    private static final int CIAN_OSCURO = Color.parseColor("#1A6C88");

    private final Paint linea = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint brillo = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint relleno = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF r = new RectF();
    private volatile int estado = ESPERA;
    private volatile float nivel = 0f;     // 0..1, volumen de tu voz
    private float suave = 0f;
    private float giro = 0f;
    private long antes = System.nanoTime();

    public Reactor(Context c) {
        super(c);
        setLayerType(LAYER_TYPE_SOFTWARE, null);  // para el brillo (blur)
        linea.setStyle(Paint.Style.STROKE);
        linea.setStrokeCap(Paint.Cap.ROUND);
        brillo.setStyle(Paint.Style.STROKE);
        brillo.setColor(CIAN);
        brillo.setMaskFilter(new BlurMaskFilter(28, BlurMaskFilter.Blur.NORMAL));
        relleno.setStyle(Paint.Style.FILL);
    }

    void estado(int e) {
        estado = e;
    }

    void nivel(float n) {
        nivel = Math.max(0f, Math.min(1f, n));
    }

    @Override
    protected void onDraw(Canvas c) {
        long ahora = System.nanoTime();
        float dt = Math.min(0.05f, (ahora - antes) / 1e9f);
        antes = ahora;
        float velocidad = estado == PENSANDO ? 260 : estado == ESCUCHANDO ? 70 : estado == HABLANDO ? 110 : 30;
        giro = (giro + velocidad * dt) % 360f;
        float objetivo = estado == ESCUCHANDO ? nivel
                : estado == HABLANDO ? 0.35f + 0.25f * (float) Math.abs(Math.sin(ahora / 9e7))
                : estado == PENSANDO ? 0.25f : 0.08f;
        suave += (objetivo - suave) * Math.min(1f, dt * 12f);

        float cx = getWidth() / 2f, cy = getHeight() / 2f;
        float R = Math.min(cx, cy) * 0.92f;

        // Halo
        brillo.setStrokeWidth(R * 0.05f);
        brillo.setAlpha((int) (90 + 120 * suave));
        c.drawCircle(cx, cy, R * (0.42f + 0.08f * suave), brillo);

        // Núcleo
        relleno.setColor(CIAN);
        relleno.setAlpha((int) (40 + 140 * suave));
        c.drawCircle(cx, cy, R * (0.16f + 0.10f * suave), relleno);
        linea.setColor(CIAN);
        linea.setAlpha(255);
        linea.setStrokeWidth(R * 0.012f);
        c.drawCircle(cx, cy, R * (0.20f + 0.10f * suave), linea);

        // Anillo de segmentos (como el reactor)
        linea.setStrokeWidth(R * 0.05f);
        r.set(cx - R * 0.42f, cy - R * 0.42f, cx + R * 0.42f, cy + R * 0.42f);
        for (int i = 0; i < 10; i++) {
            linea.setAlpha(170 + (int) (85 * suave));
            c.drawArc(r, giro + i * 36f, 26f, false, linea);
        }

        // Anillos exteriores que giran en sentidos contrarios
        linea.setStrokeWidth(R * 0.012f);
        linea.setColor(CIAN_OSCURO);
        linea.setAlpha(255);
        r.set(cx - R * 0.62f, cy - R * 0.62f, cx + R * 0.62f, cy + R * 0.62f);
        c.drawArc(r, -giro * 1.4f, 250f, false, linea);
        linea.setColor(CIAN);
        r.set(cx - R * 0.72f, cy - R * 0.72f, cx + R * 0.72f, cy + R * 0.72f);
        c.drawArc(r, giro * 0.8f + 40, 60f, false, linea);
        c.drawArc(r, giro * 0.8f + 220, 60f, false, linea);

        // Marcas alrededor (la "esfera" del HUD), que se iluminan con la voz
        linea.setStrokeWidth(R * 0.008f);
        for (int i = 0; i < 72; i++) {
            double a = Math.toRadians(i * 5 - giro * 0.3);
            float largo = (i % 6 == 0 ? 0.07f : 0.035f) + (estado == ESCUCHANDO || estado == HABLANDO
                    ? 0.06f * suave * (float) Math.abs(Math.sin(i * 0.7 + ahora / 2e8)) : 0f);
            float r1 = R * 0.84f, r2 = R * (0.84f + largo);
            linea.setColor(i % 6 == 0 ? CIAN : CIAN_OSCURO);
            c.drawLine(cx + (float) Math.cos(a) * r1, cy + (float) Math.sin(a) * r1,
                    cx + (float) Math.cos(a) * r2, cy + (float) Math.sin(a) * r2, linea);
        }
        r.set(cx - R * 0.98f, cy - R * 0.98f, cx + R * 0.98f, cy + R * 0.98f);
        linea.setColor(CIAN_OSCURO);
        c.drawArc(r, 200 + giro * 0.2f, 140f, false, linea);
        c.drawArc(r, 20 + giro * 0.2f, 140f, false, linea);

        postInvalidateOnAnimation();
    }
}
