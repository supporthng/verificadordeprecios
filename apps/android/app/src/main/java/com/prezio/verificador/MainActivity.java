package com.prezio.verificador;

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

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;

import org.json.JSONObject;
import java.io.OutputStream;

/**
 * Prezio: muestra el verificador sin internet (SITIO/equipo) a pantalla completa, como quiosco.
 * - Se actualiza sola: al abrir y cada 6 horas revisa SITIO/apps.json y, si hay versión nueva publicada
 *   en las descargas de Prezio, la descarga e instala.
 * - Pantalla siempre encendida, sin barras de Android, sin botón Atrás.
 * - Es también pantalla de inicio (HOME): el botón Inicio vuelve aquí.
 * - Con Device Owner (ver guía) bloquea por completo el equipo (lock task).
 * - Sin Device Owner: si alguien abre Recientes, la barra de notificaciones u otra app, vuelve sola
 *   al frente (necesita el permiso "Mostrar sobre otras apps" en Android 10 o más nuevo).
 * - Se sale SOLO desde el menú ⓘ › «Salir de la app», con la clave de salida del negocio.
 */
public class MainActivity extends Activity {

    static final String DIRECCION = BuildConfig.SITIO + "/equipo";
    static final String HOST_APP = Uri.parse(BuildConfig.SITIO).getHost();
    /** Solo se aceptan actualizaciones publicadas en las descargas de Prezio. */
    static final String ORIGEN_ACTUALIZACION = BuildConfig.ORIGEN_DESCARGAS;
    static final long CADA_REVISION_MS = 60L * 60 * 1000;      // cada hora
    static final long ENTRE_REVISIONES_MS = 10L * 60 * 1000;   // al volver al frente, como mucho cada 10 min

    private WebView web;
    private FrameLayout raiz;
    private final Handler hilo = new Handler(Looper.getMainLooper());
    private boolean saliendo = false;
    private long descargaId = -1;
    private BroadcastReceiver alTerminarDescarga;
    /** Vuelve a poner la app al frente si alguien salió sin la clave (Recientes, notificaciones…). */
    private final Runnable traerAlFrente = this::volverAlFrente;
    /** Pausa breve de la vigilancia (p. ej. mientras Android pregunta si fijar la app). */
    private long libreHasta = 0;

    private boolean vigilar() { return !saliendo && System.currentTimeMillis() > libreHasta; }
    private boolean revisando = false;
    private long ultimaRevision = 0;
    private int reintentos = 0;
    /** Al abrir o volver al frente: revisar si hace rato que no se revisa. */
    private final Runnable revisarAlAbrir = () -> {
        if (System.currentTimeMillis() - ultimaRevision > ENTRE_REVISIONES_MS) revisarActualizacion(false);
    };
    /** Revisión periódica de versión nueva de la app. */
    private final Runnable revisarCadaRato = new Runnable() {
        @Override public void run() {
            revisarActualizacion(false);
            hilo.postDelayed(this, CADA_REVISION_MS);
        }
    };

    @Override
    protected void onCreate(Bundle guardado) {
        super.onCreate(guardado);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON
                | WindowManager.LayoutParams.FLAG_FULLSCREEN
                | WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                | WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD
                | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
        raiz = new FrameLayout(this);
        raiz.setBackgroundColor(Color.rgb(16, 42, 67));
        setContentView(raiz);
        crearWeb();
        if (guardado != null) web.restoreState(guardado);
        else web.loadUrl(DIRECCION);
        ocultarBarras();
        activarBloqueo();
        escucharDescargas();
        hilo.postDelayed(revisarCadaRato, CADA_REVISION_MS);   // la primera revisión se hace en onResume
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
                    "window.__prezioActualizacion && window.__prezioActualizacion('" + estado + "')", null);
        });
    }

    /** Lee SITIO/apps.json; si hay un APK más nuevo publicado en las descargas de Prezio, lo instala. */
    private void revisarActualizacion(boolean avisar) {
        if (revisando || descargaId != -1) return;
        revisando = true;
        if (avisar) avisarWeb("buscando");
        new Thread(() -> {
            try {
                HttpURLConnection c = (HttpURLConnection) new URL(BuildConfig.SITIO + "/apps.json?t=" + System.currentTimeMillis()).openConnection();
                c.setConnectTimeout(15000);
                c.setReadTimeout(20000);
                c.setRequestProperty("Cache-Control", "no-cache");
                StringBuilder texto = new StringBuilder();
                try (BufferedReader r = new BufferedReader(new InputStreamReader(c.getInputStream(), "UTF-8"))) {
                    String linea;
                    while ((linea = r.readLine()) != null) texto.append(linea);
                }
                JSONObject android = new JSONObject(texto.toString()).optJSONObject("android");
                ultimaRevision = System.currentTimeMillis();
                reintentos = 0;
                int codigo = android == null ? 0 : android.optInt("codigo", 0);
                String url = android == null ? "" : android.optString("url", "");
                if (codigo > BuildConfig.VERSION_CODE && url.startsWith(ORIGEN_ACTUALIZACION) && url.endsWith(".apk")) {
                    hilo.post(() -> descargarActualizacion(url));
                } else if (avisar) {
                    avisarWeb("al_dia");
                }
            } catch (Exception e) {
                if (avisar) avisarWeb("error");
                // Sin internet todavía (p. ej. recién encendido el equipo): reintentar en un minuto.
                else if (reintentos++ < 5) hilo.postDelayed(() -> revisarActualizacion(false), 60000);
            } finally {
                revisando = false;
            }
        }, "revisar-version").start();
    }

    private void descargarActualizacion(String url) {
        DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
        if (dm == null) { avisarWeb("error"); return; }
        DownloadManager.Request pedido = new DownloadManager.Request(Uri.parse(url));
        pedido.setTitle("Prezio");
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
        descargaId = -1;
        if (!ok) { avisarWeb("error"); return; }
        // Se instala con una sesión de PackageInstaller:
        // - Bloqueo total (Device Owner): sin preguntar.
        // - Android 12 o más nuevo: sin preguntar si esta misma app instaló la versión anterior
        //   (desde la segunda actualización hecha con este botón). Si Android igual quiere
        //   confirmar, devuelve STATUS_PENDING_USER_ACTION y se muestra su pregunta (onNewIntent).
        new Thread(() -> instalarSinPreguntar(dm, id), "actualizar-app").start();
    }

    /** Respuesta de Android a la instalación (PackageInstaller). */
    @Override
    protected void onNewIntent(Intent intento) {
        super.onNewIntent(intento);
        if (intento == null || !"ACTUALIZADA".equals(intento.getAction())) return;
        int estado = intento.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
        if (estado == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            Intent confirmar = intento.getParcelableExtra(Intent.EXTRA_INTENT);
            if (confirmar == null) { avisarWeb("error"); return; }
            // Android pide confirmar: soltar el bloqueo mientras responde.
            saliendo = true;
            try { if (enModoBloqueo()) stopLockTask(); } catch (RuntimeException ignorado) { }
            avisarWeb("confirmar");
            confirmar.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            try { startActivity(confirmar); } catch (RuntimeException e) { saliendo = false; avisarWeb("error"); }
        } else if (estado != PackageInstaller.STATUS_SUCCESS) {
            saliendo = false;
            avisarWeb(estado == PackageInstaller.STATUS_FAILURE_ABORTED ? "cancelada" : "error");
        }
        // STATUS_SUCCESS: Android reemplaza la app y BootReceiver (MY_PACKAGE_REPLACED) la vuelve a abrir.
    }

    private void instalarSinPreguntar(DownloadManager dm, long id) {
        try {
            PackageInstaller instalador = getPackageManager().getPackageInstaller();
            PackageInstaller.SessionParams parametros =
                    new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
            parametros.setAppPackageName(getPackageName());
            if (Build.VERSION.SDK_INT >= 31) {
                parametros.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED);
            }
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
                // MUTABLE: Android agrega el resultado (EXTRA_STATUS) al intent.
                int banderas = PendingIntent.FLAG_UPDATE_CURRENT
                        | (Build.VERSION.SDK_INT >= 31 ? 0x02000000 /* FLAG_MUTABLE */ : 0);
                PendingIntent aviso = PendingIntent.getActivity(this, sesionId, resultado, banderas);
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
        s.setUserAgentString(s.getUserAgentString() + " PrezioApp/" + versionApp() + " (Android)");
        web.setBackgroundColor(Color.rgb(16, 42, 67));
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);
        web.setLongClickable(false);
        web.setOnLongClickListener(v -> true);   // sin menú de copiar/pegar
        web.addJavascriptInterface(new Puente(), "PrezioApp");
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
                    vista.loadData("<html><body style='font-family:sans-serif;background:#102a43;color:#f0f4f8;"
                            + "display:flex;align-items:center;justify-content:center;height:100vh;margin:0;"
                            + "text-align:center'><div><div style='font-size:52px'>📶</div><h2>Hace falta internet una vez</h2>"
                            + "<p>Conecta el equipo a internet para abrir Prezio por primera vez.<br>Se reintenta solo.</p></div></body></html>",
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
    protected void onPause() {
        super.onPause();
        if (vigilar()) hilo.postDelayed(traerAlFrente, 400);
    }

    @Override
    protected void onResume() {
        super.onResume();
        hilo.removeCallbacks(traerAlFrente);
        saliendo = false;
        hilo.removeCallbacks(revisarAlAbrir);
        hilo.postDelayed(revisarAlAbrir, 5000);   // dejar que abra y cargue los precios primero
        ocultarBarras();
        activarBloqueo();
        if (web != null) web.onResume();
    }

    @Override
    public void onWindowFocusChanged(boolean conFoco) {
        super.onWindowFocusChanged(conFoco);
        if (conFoco) {
            ocultarBarras();
        } else if (vigilar()) {
            // Bajaron la barra de notificaciones o abrieron un menú del sistema: cerrarlo.
            cerrarMenusDelSistema();
            hilo.postDelayed(() -> { if (vigilar() && !hasWindowFocus()) cerrarMenusDelSistema(); }, 300);
        }
    }

    @SuppressWarnings("deprecation")
    private void cerrarMenusDelSistema() {
        if (Build.VERSION.SDK_INT < 31) {   // desde Android 12 solo lo puede hacer el sistema
            try { sendBroadcast(new Intent(Intent.ACTION_CLOSE_SYSTEM_DIALOGS)); } catch (RuntimeException ignorado) { }
        }
    }

    /** ¿Puede la app volver sola al frente? (Android 10+ lo permite con "Mostrar sobre otras apps"). */
    private boolean puedeVolverAlFrente() {
        return Build.VERSION.SDK_INT < 29 || Settings.canDrawOverlays(this);
    }

    private void volverAlFrente() {
        if (!vigilar() || isFinishing()) return;
        try {
            ActivityManager am = (ActivityManager) getSystemService(Context.ACTIVITY_SERVICE);
            if (am != null) am.moveTaskToFront(getTaskId(), 0);
        } catch (RuntimeException ignorado) { }
        try {
            startActivity(new Intent(this, MainActivity.class)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT));
        } catch (RuntimeException ignorado) { }
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

    /** Lo que la página /equipo puede pedir (salir, solo después de comprobar la clave de salida). */
    private class Puente {
        @JavascriptInterface public boolean esApp() { return true; }
        @JavascriptInterface public void buscarActualizacion() { hilo.post(() -> revisarActualizacion(true)); }
        @JavascriptInterface public String plataforma() { return "android"; }
        @JavascriptInterface public String version() { return versionApp(); }
        @JavascriptInterface public boolean bloqueoTotal() { return esDeviceOwner(); }

        /** Botones de Android bloqueados (la app vuelve sola al frente si alguien sale). */
        @JavascriptInterface public boolean botonesBloqueados() { return esDeviceOwner() || puedeVolverAlFrente(); }

        /** Abrir el permiso "Mostrar sobre otras apps" (una sola vez por equipo). */
        @JavascriptInterface public void bloquearBotones() {
            hilo.post(() -> {
                saliendo = true;
                Intent i = new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:" + getPackageName()));
                abrir(i);
            });
        }

        /** Salir del quiosco: quitar el bloqueo y abrir los Ajustes de Android (mantenimiento). */
        @JavascriptInterface public void salir() {
            hilo.post(() -> {
                saliendo = true;
                try { if (enModoBloqueo()) stopLockTask(); } catch (RuntimeException ignorado) { }
                abrir(new Intent(Settings.ACTION_SETTINGS));
            });
        }

        /** Cerrar la app (botón ✕): quita el bloqueo y cierra, SIN abrir los Ajustes de Android. */
        @JavascriptInterface public void cerrar() {
            hilo.post(() -> {
                saliendo = true;
                hilo.removeCallbacks(traerAlFrente);
                try { if (enModoBloqueo()) stopLockTask(); } catch (RuntimeException ignorado) { }
                finishAndRemoveTask();
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
            hilo.post(() -> {
                libreHasta = System.currentTimeMillis() + 20000;   // dejar responder la pregunta de Android
                try { startLockTask(); } catch (RuntimeException ignorado) { }
            });
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
