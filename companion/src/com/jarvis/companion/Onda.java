package com.jarvis.companion;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.view.View;

/** Onda de voz del HUD: barras que suben y bajan con el volumen (tu voz al escuchar, la suya al hablar). */
public class Onda extends View {
    private final float[] niveles = new float[48];
    private int pos = 0;
    private final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
    private volatile boolean hablando = false;

    public Onda(Context c) {
        super(c);
        p.setColor(Estilo.CIAN);
        p.setStrokeCap(Paint.Cap.ROUND);
    }

    void nivel(float n) {
        synchronized (niveles) {
            niveles[pos] = Math.max(0f, Math.min(1f, n));
            pos = (pos + 1) % niveles.length;
        }
    }

    void hablando(boolean h) {
        hablando = h;
    }

    @Override
    protected void onDraw(Canvas c) {
        if (hablando) nivel(0.25f + 0.45f * (float) Math.abs(Math.sin(System.nanoTime() / 1.1e8)));
        else nivel(niveles[(pos + niveles.length - 1) % niveles.length] * 0.92f);  // se apaga suave
        float w = getWidth(), h = getHeight(), paso = w / niveles.length;
        p.setStrokeWidth(paso * 0.55f);
        synchronized (niveles) {
            for (int i = 0; i < niveles.length; i++) {
                float n = niveles[(pos + i) % niveles.length];
                float alto = Math.max(2f, n * h * 0.9f);
                p.setAlpha(80 + (int) (175 * (i / (float) niveles.length)));
                float x = i * paso + paso / 2;
                c.drawLine(x, h / 2 - alto / 2, x, h / 2 + alto / 2, p);
            }
        }
        postInvalidateDelayed(40);
    }
}
