package com.supporthng.consultaprecios;

import android.app.Activity;
import android.app.ActivityManager;
import android.app.DownloadManager;
import android.app.PendingIntent;
import android.app.admin.DevicePolicyManager;
import android.content.BroadcastReceiver;
import android.content.IntentFilter;
import android.content.pm.PackageInstaller;
import android.database.Cursor;
import android.os.ParcelFileDescriptor;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;

import java.io.InputStream;
import java.io.OutputStream;

/**
 * Consulta de Precios: muestra la app sin internet (GitHub Pages) a pantalla completa, como quiosco.
 * - Pantalla siempre encendida, sin barras de Android, sin botón Atrás.
 * - Es también pantalla de inicio (HOME): el botón Inicio vuelve aquí.
 * - Con Device Owner (ver guía) bloquea por completo el equipo (lock task).
 * - Se sale SOLO desde el menú ✕ de la app, con la clave de salida del verificador.
 */
public class MainActivity extends Activity {

    static final String DIRECCION = "https://supporthng.github.io/verificadordeprecios/";
    static final String HOST_APP = "supporthng.github.io";
    /** Solo se aceptan actualizaciones publicadas en el repositorio del negocio. */
    static final String ORIGEN_ACTUALIZACION = "https://github.com/supporthng/verificadordeprecios/releases/download/";

    private WebView web;
    private FrameLayout raiz;
    private final Handler hilo = new Handler(Looper.getMainLooper());
    private boolean saliendo = false;
    private long descargaId = -1;
    private BroadcastReceiver alTerminarDescarga;

    @Override
    protected void onCreate(Bundle guardado) {
        super.onCreate(guardado);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON
                | WindowManager.LayoutParams.FLAG_FULLSCREEN
                | WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                | WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD
                | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
        raiz = new FrameLayout(this);
        raiz.setBackgroundColor(Color.rgb(244, 248, 255));
        setContentView(raiz);
        crearWeb();
        if (guardado != null) web.restoreState(guardado);
        else web.loadUrl(DIRECCION);
        ocultarBarras();
        activarBloqueo();
        escucharDescargas();
    }

    @Override
    protected void onDestroy() {
        if (alTerminarDescarga != null) {
            try { unregisterReceiver(alTerminarDescarga); } catch (RuntimeException ignorado) { }
        }
        super.onDestroy();
    }

    // ------------------------------------------------------------ actualizar la app
    private void escucharDescargas() {
        alTerminarDescarga = new BroadcastReceiver() {
            @Override
            public void onReceive(Context ctx, Intent i) {
                long id = i.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1);
                if (id != -1 && id == descargaId) instalarDescarga(id);
            }
        };
        IntentFilter filtro = new IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE);
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(alTerminarDescarga, filtro, 0x2 /* RECEIVER_EXPORTED */);
        else registerReceiver(alTerminarDescarga, filtro);
    }

    private void avisarWeb(String estado) {
        hilo.post(() -> {
            if (web != null) web.evaluateJavascript(
                    "window.__actualizacionApp && window.__actualizacionApp('" + estado + "')", null);
        });
    }

    private void descargarActualizacion(String url) {
        DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
        if (dm == null) { avisarWeb("error"); return; }
        DownloadManager.Request pedido = new DownloadManager.Request(Uri.parse(url));
        pedido.setTitle("Consulta de Precios");
        pedido.setDescription("Descargando la versión nueva de la app");
        pedido.setMimeType("application/vnd.android.package-archive");
        pedido.setDestinationInExternalFilesDir(this, null, "actualizacion-" + System.currentTimeMillis() + ".apk");
        pedido.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE);
        descargaId = dm.enqueue(pedido);
        avisarWeb("descargando");
    }

    private void instalarDescarga(long id) {
        DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
        boolean ok = false;
        try (Cursor c = dm.query(new DownloadManager.Query().setFilterById(id))) {
            if (c != null && c.moveToFirst()) {
                int col = c.getColumnIndex(DownloadManager.COLUMN_STATUS);
                ok = col >= 0 && c.getInt(col) == DownloadManager.STATUS_SUCCESSFUL;
            }
        }
        if (!ok) { avisarWeb("error"); return; }
        if (esDeviceOwner()) {
            // Bloqueo total: instalar sin preguntar (y la app se vuelve a abrir sola).
            new Thread(() -> instalarSinPreguntar(dm, id), "actualizar-app").start();
            return;
        }
        // Sin bloqueo total, Android pide confirmar: hay que soltar el bloqueo de pantalla.
        avisarWeb("instalando");
        hilo.post(() -> {
            saliendo = true;
            try { if (enModoBloqueo()) stopLockTask(); } catch (RuntimeException ignorado) { }
            Uri archivo = dm.getUriForDownloadedFile(id);
            Intent instalar = new Intent(Intent.ACTION_VIEW);
            instalar.setDataAndType(archivo, "application/vnd.android.package-archive");
            instalar.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
            try { startActivity(instalar); } catch (RuntimeException e) { avisarWeb("error"); }
        });
    }

    private void instalarSinPreguntar(DownloadManager dm, long id) {
        try {
            PackageInstaller instalador = getPackageManager().getPackageInstaller();
            PackageInstaller.SessionParams parametros =
                    new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
            parametros.setAppPackageName(getPackageName());
            int sesionId = instalador.createSession(parametros);
            try (PackageInstaller.Session sesion = instalador.openSession(sesionId);
                 InputStream entrada = new ParcelFileDescriptor.AutoCloseInputStream(dm.openDownloadedFile(id));
                 OutputStream salida = sesion.openWrite("app", 0, -1)) {
                byte[] bufer = new byte[65536];
                int n;
                while ((n = entrada.read(bufer)) > 0) salida.write(bufer, 0, n);
                sesion.fsync(salida);
                salida.close();
                Intent resultado = new Intent(this, MainActivity.class).setAction("ACTUALIZADA");
                PendingIntent aviso = PendingIntent.getActivity(this, sesionId, resultado,
                        PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
                avisarWeb("instalando");
                sesion.commit(aviso.getIntentSender());
            }
        } catch (Exception e) {
            avisarWeb("error");
        }
    }

    private void crearWeb() {
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);       // IndexedDB / localStorage: los precios guardados
        s.setDatabaseEnabled(true);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setDisplayZoomControls(false);
        s.setAllowFileAccess(false);
        s.setUserAgentString(s.getUserAgentString() + " ConsultaPreciosApp/" + versionApp() + " (Android)");
        web.setBackgroundColor(Color.rgb(244, 248, 255));
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);
        web.setLongClickable(false);
        web.setOnLongClickListener(v -> true);   // sin menú de copiar/pegar
        web.addJavascriptInterface(new Puente(), "AndroidKiosco");
        web.setWebChromeClient(new WebChromeClient());
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView vista, WebResourceRequest pedido) {
                // Solo la app; cualquier otro enlace se ignora (el cliente no puede navegar fuera).
                Uri u = pedido.getUrl();
                return u == null || !HOST_APP.equalsIgnoreCase(u.getHost());
            }

            @Override
            public void onReceivedError(WebView vista, WebResourceRequest pedido, WebResourceError error) {
                // Primera vez sin internet (todavía no hay copia guardada): reintentar solo.
                if (pedido != null && pedido.isForMainFrame()) {
                    vista.loadData("<html><body style='font-family:sans-serif;background:#f4f8ff;color:#102b50;"
                            + "display:flex;align-items:center;justify-content:center;height:100vh;margin:0;"
                            + "text-align:center'><div><div style='font-size:52px'>📶</div><h2>Hace falta internet una vez</h2>"
                            + "<p>Conecta el equipo a internet para descargar los precios.<br>Se reintenta solo.</p></div></body></html>",
                            "text/html; charset=utf-8", "utf-8");
                    hilo.postDelayed(() -> { if (web != null) web.loadUrl(DIRECCION); }, 15000);
                }
            }

            @Override
            public boolean onRenderProcessGone(WebView vista, RenderProcessGoneDetail detalle) {
                // Si el motor web se cae, crear uno nuevo y volver a abrir la app.
                raiz.removeView(vista);
                vista.destroy();
                crearWeb();
                web.loadUrl(DIRECCION);
                return true;
            }
        });
        raiz.addView(web, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));
        web.requestFocus();
    }

    @Override
    protected void onSaveInstanceState(Bundle estado) {
        super.onSaveInstanceState(estado);
        if (web != null) web.saveState(estado);
    }

    @Override
    protected void onResume() {
        super.onResume();
        saliendo = false;
        ocultarBarras();
        activarBloqueo();
        if (web != null) web.onResume();
    }

    @Override
    public void onWindowFocusChanged(boolean conFoco) {
        super.onWindowFocusChanged(conFoco);
        if (conFoco) ocultarBarras();
    }

    @Override
    public void onBackPressed() {
        // Sin botón Atrás: el cliente no puede salir.
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent evento) {
        int k = evento.getKeyCode();
        if (k == KeyEvent.KEYCODE_BACK || k == KeyEvent.KEYCODE_APP_SWITCH || k == KeyEvent.KEYCODE_MENU) return true;
        return super.dispatchKeyEvent(evento);
    }

    @SuppressWarnings("deprecation")
    private void ocultarBarras() {
        getWindow().getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                        | View.SYSTEM_UI_FLAG_FULLSCREEN
                        | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                        | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN);
    }

    private boolean esDeviceOwner() {
        DevicePolicyManager dpm = (DevicePolicyManager) getSystemService(Context.DEVICE_POLICY_SERVICE);
        return dpm != null && dpm.isDeviceOwnerApp(getPackageName());
    }

    private boolean enModoBloqueo() {
        ActivityManager am = (ActivityManager) getSystemService(Context.ACTIVITY_SERVICE);
        if (am == null) return false;
        if (Build.VERSION.SDK_INT >= 23) return am.getLockTaskModeState() != ActivityManager.LOCK_TASK_MODE_NONE;
        return am.isInLockTaskMode();
    }

    /** Con Device Owner: bloqueo total (sin Inicio, sin recientes, sin barra de notificaciones). */
    private void activarBloqueo() {
        if (saliendo || !esDeviceOwner()) return;
        try {
            DevicePolicyManager dpm = (DevicePolicyManager) getSystemService(Context.DEVICE_POLICY_SERVICE);
            ComponentName admin = new ComponentName(this, AdminReceiver.class);
            dpm.setLockTaskPackages(admin, new String[]{getPackageName(), "com.android.settings"});
            if (!enModoBloqueo()) startLockTask();
        } catch (RuntimeException e) {
            // Si falla, la app sigue funcionando como pantalla de inicio.
        }
    }

    private String versionApp() {
        try {
            PackageInfo p = getPackageManager().getPackageInfo(getPackageName(), 0);
            return p.versionName;
        } catch (Exception e) {
            return "1";
        }
    }

    /** Lo que la app web puede pedir (solo después de la clave de salida del menú ✕). */
    private class Puente {
        @JavascriptInterface public boolean esApp() { return true; }
        @JavascriptInterface public String plataforma() { return "android"; }
        @JavascriptInterface public String version() { return versionApp(); }
        @JavascriptInterface public boolean bloqueoTotal() { return esDeviceOwner(); }

        /** Salir del quiosco: quitar el bloqueo y abrir los Ajustes de Android (mantenimiento). */
        @JavascriptInterface public void salir() {
            hilo.post(() -> {
                saliendo = true;
                try { if (enModoBloqueo()) stopLockTask(); } catch (RuntimeException ignorado) { }
                abrir(new Intent(Settings.ACTION_SETTINGS));
            });
        }

        /** Elegir otra pantalla de inicio (para dejar de usar el equipo como verificador). */
        @JavascriptInterface public void cambiarInicio() {
            hilo.post(() -> {
                saliendo = true;
                try { if (enModoBloqueo()) stopLockTask(); } catch (RuntimeException ignorado) { }
                abrir(new Intent(Settings.ACTION_HOME_SETTINGS));
            });
        }

        /** Sin Device Owner: fijar la app en pantalla (Android pide confirmar una vez). */
        @JavascriptInterface public void fijar() {
            hilo.post(() -> { try { startLockTask(); } catch (RuntimeException ignorado) { } });
        }

        /** Descargar e instalar la versión nueva de la app (solo desde el repositorio del negocio). */
        @JavascriptInterface public boolean actualizar(String url) {
            if (url == null || !url.startsWith(ORIGEN_ACTUALIZACION) || !url.endsWith(".apk")) return false;
            hilo.post(() -> descargarActualizacion(url));
            return true;
        }

        /** Recargar la app (por ejemplo, tras una actualización). */
        @JavascriptInterface public void recargar() {
            hilo.post(() -> { if (web != null) web.reload(); });
        }
    }

    private void abrir(Intent intento) {
        intento.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try { startActivity(intento); } catch (RuntimeException e) {
            try { startActivity(new Intent(Settings.ACTION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); }
            catch (RuntimeException ignorado) { }
        }
    }
}
