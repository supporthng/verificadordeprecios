package com.supporthng.consultaprecios;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Al encender el equipo, abrir la Consulta de Precios. */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null || !Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) return;
        Intent abrir = new Intent(context, MainActivity.class);
        abrir.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        try {
            context.startActivity(abrir);
        } catch (RuntimeException e) {
            // Android 10+ puede impedirlo; como la app también es la pantalla de inicio, abre igual.
        }
    }
}
