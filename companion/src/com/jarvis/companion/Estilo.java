package com.jarvis.companion;

import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.view.Gravity;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.TextView;

/** El estilo de JARVIS (diseño propio): fondo casi negro, cian holográfico, letras técnicas y paneles con borde. */
final class Estilo {
    static final int FONDO = Color.parseColor("#02070D");
    static final int PANEL = Color.parseColor("#B3061520");
    static final int CIAN = Color.parseColor("#4FD8FF");
    static final int CIAN_TENUE = Color.parseColor("#7FB8CC");
    static final int CIAN_OSCURO = Color.parseColor("#1A6C88");
    static final int BLANCO = Color.parseColor("#E6F7FF");
    static final int VERDE = Color.parseColor("#3DFF9A");
    static final int ROJO = Color.parseColor("#FF4D5E");
    static final int AMBAR = Color.parseColor("#FFB547");

    private Estilo() {}

    static int dp(Context c, float v) {
        return Math.round(v * c.getResources().getDisplayMetrics().density);
    }

    static TextView texto(Context c, String s, float tam, int color, boolean mono) {
        TextView t = new TextView(c);
        t.setText(s);
        t.setTextSize(tam);
        t.setTextColor(color);
        t.setTypeface(mono ? Typeface.MONOSPACE : Typeface.create("sans-serif-light", Typeface.NORMAL));
        t.setLetterSpacing(mono ? 0.08f : 0.04f);
        return t;
    }

    /** Rótulo pequeño en mayúsculas con brillo («ENLACE PC»). */
    static TextView rotulo(Context c, String s) {
        TextView t = texto(c, s.toUpperCase(), 10, CIAN_TENUE, true);
        t.setLetterSpacing(0.22f);
        return t;
    }

    /** Fondo de panel: oscuro translúcido con borde cian fino y esquinas apenas redondeadas. */
    static GradientDrawable marco(Context c, int borde) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(PANEL);
        g.setStroke(dp(c, 1), borde);
        g.setCornerRadius(dp(c, 4));
        return g;
    }

    /** Botón «neón»: texto cian en mayúsculas, borde que se ilumina al pulsar. */
    static TextView boton(Context c, String s, View.OnClickListener al) {
        TextView b = texto(c, s.toUpperCase(), 12, CIAN, true);
        b.setLetterSpacing(0.15f);
        b.setGravity(Gravity.CENTER);
        int p = dp(c, 14);
        b.setPadding(p, p, p, p);
        StateListDrawable fondo = new StateListDrawable();
        GradientDrawable pulsado = marco(c, CIAN);
        pulsado.setColor(Color.parseColor("#334FD8FF"));
        fondo.addState(new int[]{android.R.attr.state_pressed}, pulsado);
        fondo.addState(new int[]{}, marco(c, CIAN_OSCURO));
        b.setBackground(fondo);
        b.setClickable(true);
        b.setOnClickListener(al);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, dp(c, 6), 0, 0);
        b.setLayoutParams(lp);
        return b;
    }

    /** Tarjeta de estado: rótulo + valor + luz (verde, ámbar o roja). Devuelve {tarjeta, valor, luz}. */
    static View[] tarjeta(Context c, String rotulo) {
        LinearLayout t = new LinearLayout(c);
        t.setOrientation(LinearLayout.VERTICAL);
        int p = dp(c, 10);
        t.setPadding(p, p, p, p);
        t.setBackground(marco(c, CIAN_OSCURO));
        LinearLayout fila = new LinearLayout(c);
        fila.setGravity(Gravity.CENTER_VERTICAL);
        View luz = new View(c);
        GradientDrawable punto = new GradientDrawable();
        punto.setShape(GradientDrawable.OVAL);
        punto.setColor(AMBAR);
        luz.setBackground(punto);
        fila.addView(luz, new LinearLayout.LayoutParams(dp(c, 8), dp(c, 8)));
        TextView r = rotulo(c, rotulo);
        r.setPadding(dp(c, 6), 0, 0, 0);
        fila.addView(r);
        TextView valor = texto(c, "—", 14, BLANCO, false);
        valor.setPadding(0, dp(c, 4), 0, 0);
        t.addView(fila);
        t.addView(valor);
        return new View[]{t, valor, luz};
    }

    static void luz(View luz, int color) {
        ((GradientDrawable) luz.getBackground()).setColor(color);
    }
}
