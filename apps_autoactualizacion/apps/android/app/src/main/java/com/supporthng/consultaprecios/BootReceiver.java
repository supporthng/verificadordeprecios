package com.supporthng.consultaprecios;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Al encender el equipo (o tras actualizar la app), abrir la Consulta de Precios. */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        // Al encender el equipo o después de actualizar la app: volver a abrir el verificador.
        if (intent == null) return;
        String accion = intent.getAction();
        if (!Intent.ACTION_BOOT_COMPLETED.equals(accion) && !Intent.ACTION_MY_PACKAGE_REPLACED.equals(accion)) return;
        Intent abrir = new Intent(context, MainActivity.class);
        abrir.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        try {
            context.startActivity(abrir);
        } catch (RuntimeException e) {
            // Android 10+ puede impedirlo; como la app también es la pantalla de inicio, abre igual.
        }
    }
}
