package com.idoltimex.localrelay;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;

public final class RelayConfig {
    private static final String TAG = "LocalRelayConfig";
    private static final String PREFS = "local_relay_config";
    private static final String ENABLED = "enabled";
    private static final String BACKEND_HOST = "backend_host";
    private static final String BACKEND_PORT = "backend_port";
    private static final String GAME_HOST = "game_host";
    private static final String GAME_PORT = "game_port";

    public static final String DEFAULT_BACKEND_HOST = "127.0.0.1";
    public static final int DEFAULT_BACKEND_PORT = 8080;
    public static final String DEFAULT_GAME_HOST = "127.0.0.1";
    public static final int DEFAULT_GAME_PORT = 21001;
    public static final int LOCAL_BACKEND_PORT = 8080;
    public static final int LOCAL_GAME_PORT = 21001;

    private RelayConfig() {
    }

    public static final class Values {
        public final boolean enabled;
        public final String backendHost;
        public final int backendPort;
        public final String gameHost;
        public final int gamePort;

        public Values(boolean enabled, String backendHost, int backendPort,
                String gameHost, int gamePort) {
            this.enabled = enabled;
            this.backendHost = backendHost;
            this.backendPort = backendPort;
            this.gameHost = gameHost;
            this.gamePort = gamePort;
        }

        public Values withEnabled(boolean value) {
            return new Values(value, backendHost, backendPort, gameHost, gamePort);
        }
    }

    private static SharedPreferences prefs(Context context) {
        return context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    public static boolean isEnabled(Context context) {
        return prefs(context).getBoolean(ENABLED, true);
    }

    public static String getBackendHost(Context context) {
        return prefs(context).getString(BACKEND_HOST, DEFAULT_BACKEND_HOST);
    }

    public static int getBackendPort(Context context) {
        return prefs(context).getInt(BACKEND_PORT, DEFAULT_BACKEND_PORT);
    }

    public static String getGameHost(Context context) {
        return prefs(context).getString(GAME_HOST, DEFAULT_GAME_HOST);
    }

    public static int getGamePort(Context context) {
        return prefs(context).getInt(GAME_PORT, DEFAULT_GAME_PORT);
    }

    public static Values snapshot(Context context) {
        return new Values(isEnabled(context), getBackendHost(context), getBackendPort(context),
                getGameHost(context), getGamePort(context));
    }

    public static String describe(Context context) {
        return "enabled=" + isEnabled(context)
                + " backend=" + getBackendHost(context) + ":" + getBackendPort(context)
                + " game=" + getGameHost(context) + ":" + getGamePort(context);
    }

    public static void save(Context context, boolean enabled, String backendHost, int backendPort,
            String gameHost, int gamePort) {
        save(context, new Values(enabled, backendHost, backendPort, gameHost, gamePort));
    }

    public static void save(Context context, Values values) {
        prefs(context).edit()
                .putBoolean(ENABLED, values.enabled)
                .putString(BACKEND_HOST, values.backendHost)
                .putInt(BACKEND_PORT, values.backendPort)
                .putString(GAME_HOST, values.gameHost)
                .putInt(GAME_PORT, values.gamePort)
                .apply();
        Log.i(TAG, "configuration saved: enabled=" + values.enabled
                + " backend=" + values.backendHost + ":" + values.backendPort
                + " game=" + values.gameHost + ":" + values.gamePort);
    }
}
