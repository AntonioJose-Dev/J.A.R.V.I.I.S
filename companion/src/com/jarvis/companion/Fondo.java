package com.jarvis.companion;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.RadialGradient;
import android.graphics.Shader;
import android.view.View;

/** Fondo del HUD: degradado profundo, rejilla tenue, esquinas de visor y una línea de escaneo que baja. */
public class Fondo extends View {
    private final Paint rejilla = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint esquina = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint escaneo = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint luz = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final boolean opaco;

    public Fondo(Context c, boolean opaco) {
        super(c);
        this.opaco = opaco;
        rejilla.setColor(Color.parseColor("#0F4FD8FF"));
        rejilla.setStrokeWidth(1);
        esquina.setColor(Estilo.CIAN);
        esquina.setStrokeWidth(Estilo.dp(c, 2));
        esquina.setStyle(Paint.Style.STROKE);
    }

    @Override
    protected void onDraw(Canvas c) {
        int w = getWidth(), h = getHeight();
        if (opaco) c.drawColor(Estilo.FONDO);
        // Halo central
        luz.setShader(new RadialGradient(w / 2f, h * 0.38f, Math.max(w, h) * 0.55f,
                Color.parseColor("#2A0E5C78"), Color.TRANSPARENT, Shader.TileMode.CLAMP));
        c.drawRect(0, 0, w, h, luz);
        // Rejilla
        int paso = Estilo.dp(getContext(), 28);
        for (int x = 0; x < w; x += paso) c.drawLine(x, 0, x, h, rejilla);
        for (int y = 0; y < h; y += paso) c.drawLine(0, y, w, y, rejilla);
        // Esquinas de visor
        float m = Estilo.dp(getContext(), 14), l = Estilo.dp(getContext(), 26);
        c.drawLine(m, m, m + l, m, esquina);
        c.drawLine(m, m, m, m + l, esquina);
        c.drawLine(w - m, m, w - m - l, m, esquina);
        c.drawLine(w - m, m, w - m, m + l, esquina);
        c.drawLine(m, h - m, m + l, h - m, esquina);
        c.drawLine(m, h - m, m, h - m - l, esquina);
        c.drawLine(w - m, h - m, w - m - l, h - m, esquina);
        c.drawLine(w - m, h - m, w - m, h - m - l, esquina);
        // Escaneo
        float y = (System.currentTimeMillis() % 4000L) / 4000f * h;
        escaneo.setShader(new LinearGradient(0, y - 40, 0, y, Color.TRANSPARENT, Color.parseColor("#334FD8FF"),
                Shader.TileMode.CLAMP));
        c.drawRect(0, y - 40, w, y, escaneo);
        postInvalidateDelayed(33);
    }
}
