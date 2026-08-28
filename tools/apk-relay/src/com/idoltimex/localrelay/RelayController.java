package com.idoltimex.localrelay;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

public final class RelayController {
    private static final String TAG = "LocalRelay";
    private static final long START_TIMEOUT_MS = 10000L;
    private static final long LATENCY_INITIAL_DELAY_MS = 1000L;
    private static final long LATENCY_INTERVAL_MS = 5000L;
    private static final int LATENCY_CONNECT_TIMEOUT_MS = 3000;
    private static final Object LOCK = new Object();
    private static final Handler MAIN_HANDLER = new Handler(Looper.getMainLooper());
    private static Context appContext;
    private static ExecutorService executor;
    private static Listener httpListener;
    private static Listener gameListener;
    private static volatile String lastError = "";
    private static State state = State.STOPPED;
    private static String statusNote = "";
    private static Attempt activeAttempt;
    private static long nextAttemptId;
    private static Runnable timeoutTask;
    private static boolean readyLogged;

    private RelayController() {
    }

    public enum State {
        STOPPED,
        STARTING,
        RUNNING,
        FAILED
    }

    public interface StatusListener {
        void onStarting();

        void onRunning();

        void onStopped();

        void onFailed(String message);

        void onLatencyChanged();
    }

    public static void start(Context context) {
        Context app = context.getApplicationContext();
        RelayConfig.Values values = RelayConfig.snapshot(app);
        if (!values.enabled) {
            stop(context);
            return;
        }
        beginAttempt(app, values, values, false, null, false);
    }

    public static void ensureStarted(Context context) {
        Context app = context.getApplicationContext();
        RelayConfig.Values values = RelayConfig.snapshot(app);
        synchronized (LOCK) {
            appContext = app;
            if (!values.enabled) {
                cancelTimeoutLocked();
                if (state != State.STOPPED || httpListener != null || gameListener != null) {
                    Log.i(TAG, "ensureStarted stopping disabled relay");
                    stopLocked();
                    activeAttempt = null;
                    state = State.STOPPED;
                    statusNote = "";
                }
                return;
            }
            if (state == State.STARTING || state == State.RUNNING) {
                Log.d(TAG, "ensureStarted no-op: state=" + state);
                return;
            }
        }
        Log.i(TAG, "ensureStarted restarting relay after lifecycle transition");
        beginAttempt(app, values, values, false, null, false);
    }

    public static void stop(Context context) {
        StatusListener listener;
        synchronized (LOCK) {
            appContext = context.getApplicationContext();
            Log.i(TAG, "stop requested");
            nextAttemptId++;
            cancelTimeoutLocked();
            listener = activeAttempt == null ? null : activeAttempt.listener;
            stopLocked();
            activeAttempt = null;
            lastError = "已停止";
            statusNote = "";
            state = State.STOPPED;
        }
        dispatchStopped(listener);
    }

    public static void restart(Context context, RelayConfig.Values next, StatusListener listener) {
        Context app = context.getApplicationContext();
        RelayConfig.Values previous = RelayConfig.snapshot(app);
        if (!next.enabled) {
            StatusListener activeListener;
            synchronized (LOCK) {
                activeListener = activeAttempt == null ? null : activeAttempt.listener;
            }
            RelayConfig.save(app, next);
            stop(context);
            if (listener != null && listener != activeListener) {
                dispatchStopped(listener);
            }
            return;
        }
        beginAttempt(app, next, previous, previous.enabled, listener, false);
    }

    public static void removeStatusListener(StatusListener listener) {
        synchronized (LOCK) {
            if (activeAttempt != null && activeAttempt.listener == listener) {
                activeAttempt.listener = null;
            }
        }
    }

    public static void observe(final StatusListener listener) {
        if (listener == null) {
            return;
        }
        synchronized (LOCK) {
            if (activeAttempt != null) {
                activeAttempt.listener = listener;
            }
        }
        MAIN_HANDLER.post(new Runnable() {
            @Override
            public void run() {
                State current;
                String error;
                synchronized (LOCK) {
                    current = state;
                    error = lastError;
                }
                if (current == State.STARTING) {
                    listener.onStarting();
                } else if (current == State.RUNNING) {
                    listener.onRunning();
                } else if (current == State.FAILED) {
                    listener.onFailed(error);
                } else {
                    listener.onStopped();
                }
            }
        });
    }

    public static boolean isRunning() {
        synchronized (LOCK) {
            return state == State.RUNNING && httpListener != null && gameListener != null
                    && httpListener.isListening() && gameListener.isListening();
        }
    }

    public static String getStatus() {
        synchronized (LOCK) {
            if (state == State.RUNNING) {
                return runningStatusLocked(activeAttempt);
            }
            if (state == State.STARTING) {
                return statusNote == null || statusNote.isEmpty() ? "启动中…" : statusNote;
            }
            if (state == State.FAILED) {
                return "启动失败：" + lastError;
            }
            return "已停止";
        }
    }

    private static String runningStatusLocked(Attempt attempt) {
        StringBuilder status = new StringBuilder();
        if (statusNote != null && !statusNote.isEmpty()) {
            status.append(statusNote).append('\n');
        }
        status.append("运行中\n")
                .append("后台 HTTP 8080\n")
                .append("游戏 TCP 21001\n");
        if (attempt == null) {
            status.append("延迟：后台 检测中…\n")
                    .append("延迟：游戏 检测中…");
            return status.toString();
        }
        status.append("延迟：后台 ")
                .append(formatLatency(attempt.backendLatencyMs, attempt.backendLatencyMeasured))
                .append('\n')
                .append("延迟：游戏 ")
                .append(formatLatency(attempt.gameLatencyMs, attempt.gameLatencyMeasured));
        return status.toString();
    }

    private static String formatLatency(long latencyMs, boolean measured) {
        if (!measured) {
            return "检测中…";
        }
        return latencyMs < 0 ? "不可达" : latencyMs + " ms";
    }

    public static State getState() {
        synchronized (LOCK) {
            return state;
        }
    }

    private static void beginAttempt(Context context, RelayConfig.Values values,
            RelayConfig.Values previous, boolean restorePrevious, StatusListener listener,
            boolean recovery) {
        Attempt attempt;
        synchronized (LOCK) {
            appContext = context.getApplicationContext();
            cancelTimeoutLocked();
            stopLocked();
            attempt = new Attempt(++nextAttemptId, values, previous, restorePrevious, recovery, listener);
            activeAttempt = attempt;
            state = State.STARTING;
            statusNote = recovery ? "新配置失败，正在恢复旧配置…" : "正在启动…";
            lastError = "";
            readyLogged = false;
            executor = Executors.newCachedThreadPool();
            httpListener = new Listener(attempt, "HTTP", RelayConfig.LOCAL_BACKEND_PORT,
                    values.backendHost, values.backendPort);
            gameListener = new Listener(attempt, "GAME", RelayConfig.LOCAL_GAME_PORT,
                    values.gameHost, values.gamePort);
            attempt.http = httpListener;
            attempt.game = gameListener;
            timeoutTask = new Runnable() {
                @Override
                public void run() {
                    onAttemptTimeout(attempt.id);
                }
            };
            MAIN_HANDLER.postDelayed(timeoutTask, START_TIMEOUT_MS);
            // Queue the initial event before worker threads can report a bound listener.
            dispatchStarting(listener);
            executor.execute(httpListener);
            executor.execute(gameListener);
            Log.i(TAG, "listener tasks submitted: http=127.0.0.1:" + RelayConfig.LOCAL_BACKEND_PORT
                    + " -> " + values.backendHost + ":" + values.backendPort
                    + " game=127.0.0.1:" + RelayConfig.LOCAL_GAME_PORT
                    + " -> " + values.gameHost + ":" + values.gamePort
                    + " attempt=" + attempt.id);
        }
    }

    private static void stopLocked() {
        if (activeAttempt != null && activeAttempt.latencyExecutor != null) {
            Log.d(TAG, "shutting down latency monitor");
            activeAttempt.latencyExecutor.shutdownNow();
            activeAttempt.latencyExecutor = null;
        }
        if (httpListener != null) {
            Log.d(TAG, "closing HTTP listener");
            httpListener.close();
            httpListener = null;
        }
        if (gameListener != null) {
            Log.d(TAG, "closing GAME listener");
            gameListener.close();
            gameListener = null;
        }
        if (executor != null) {
            Log.d(TAG, "shutting down relay executor");
            executor.shutdownNow();
            executor = null;
        }
    }

    private static void listenerBound(Listener listener) {
        StatusListener callback = null;
        synchronized (LOCK) {
            Attempt attempt = activeAttempt;
            if (attempt == null || attempt.id != listener.attempt.id || attempt.failed
                    || state != State.STARTING || listener.bound) {
                return;
            }
            listener.bound = true;
            attempt.boundCount++;
            if (attempt.boundCount == 2 && !readyLogged) {
                readyLogged = true;
                state = State.RUNNING;
                lastError = "";
                statusNote = attempt.recovery ? "新配置失败，已恢复旧配置" : "";
                cancelTimeoutLocked();
                if (!attempt.recovery) {
                    RelayConfig.save(appContext, attempt.values);
                }
                startLatencyMonitorLocked(attempt);
                callback = attempt.listener;
                Log.i(TAG, "relay ready: HTTP and GAME listeners are bound attempt=" + attempt.id);
            }
        }
        dispatchRunning(callback);
    }

    private static void startLatencyMonitorLocked(final Attempt attempt) {
        if (attempt.latencyExecutor != null) {
            return;
        }
        attempt.latencyExecutor = Executors.newScheduledThreadPool(2);
        attempt.latencyExecutor.scheduleAtFixedRate(new Runnable() {
            @Override
            public void run() {
                probeLatency(attempt, true);
            }
        }, LATENCY_INITIAL_DELAY_MS, LATENCY_INTERVAL_MS, TimeUnit.MILLISECONDS);
        attempt.latencyExecutor.scheduleAtFixedRate(new Runnable() {
            @Override
            public void run() {
                probeLatency(attempt, false);
            }
        }, LATENCY_INITIAL_DELAY_MS, LATENCY_INTERVAL_MS, TimeUnit.MILLISECONDS);
    }

    private static void probeLatency(Attempt attempt, boolean backend) {
        String host;
        int port;
        synchronized (LOCK) {
            if (activeAttempt != attempt || attempt.failed || state != State.RUNNING) {
                return;
            }
            host = backend ? attempt.values.backendHost : attempt.values.gameHost;
            port = backend ? attempt.values.backendPort : attempt.values.gamePort;
        }

        long latencyMs = -1L;
        Socket socket = null;
        try {
            long startedAt = System.nanoTime();
            socket = new Socket();
            socket.connect(new InetSocketAddress(host, port), LATENCY_CONNECT_TIMEOUT_MS);
            latencyMs = Math.max(0L, (System.nanoTime() - startedAt) / 1000000L);
        } catch (Exception ignored) {
            // A failed probe only updates the displayed latency; it does not stop Relay.
        } finally {
            if (socket != null) {
                try {
                    socket.close();
                } catch (IOException ignored) {
                }
            }
        }

        StatusListener callback = null;
        synchronized (LOCK) {
            if (activeAttempt != attempt || attempt.failed || state != State.RUNNING) {
                return;
            }
            if (backend) {
                attempt.backendLatencyMs = latencyMs;
                attempt.backendLatencyMeasured = true;
            } else {
                attempt.gameLatencyMs = latencyMs;
                attempt.gameLatencyMeasured = true;
            }
            callback = attempt.listener;
        }
        dispatchLatency(attempt, callback);
    }

    private static void listenerFailed(Listener listener, String message) {
        failAttempt(listener.attempt, message);
    }

    private static void onAttemptTimeout(long attemptId) {
        Attempt attempt;
        synchronized (LOCK) {
            attempt = activeAttempt;
            if (attempt == null || attempt.id != attemptId) {
                return;
            }
        }
        failAttempt(attempt, "HTTP/TCP 本地监听在 10 秒内未同时就绪");
    }

    private static void failAttempt(Attempt attempt, String message) {
        StatusListener callback;
        boolean restore;
        RelayConfig.Values restoreValues;
        synchronized (LOCK) {
            if (activeAttempt != attempt || attempt.failed) {
                return;
            }
            attempt.failed = true;
            cancelTimeoutLocked();
            stopLocked();
            callback = attempt.listener;
            restore = attempt.restorePrevious && !attempt.recovery
                    && attempt.previous != null && attempt.previous.enabled;
            restoreValues = attempt.previous;
            // Detach the failed attempt before recovery starts so late worker callbacks are stale.
            activeAttempt = null;
            if (!restore) {
                state = State.FAILED;
                statusNote = "";
                lastError = message;
            }
        }
        if (restore) {
            Log.w(TAG, "relay attempt failed; restoring previous configuration: " + message);
            beginAttempt(appContext, restoreValues, restoreValues, false, callback, true);
        } else {
            Log.e(TAG, "relay startup failed: " + message);
            dispatchFailed(callback, message);
        }
    }

    private static void cancelTimeoutLocked() {
        if (timeoutTask != null) {
            MAIN_HANDLER.removeCallbacks(timeoutTask);
            timeoutTask = null;
        }
    }

    private static void dispatchStarting(final StatusListener listener) {
        if (listener == null) {
            return;
        }
        MAIN_HANDLER.post(new Runnable() {
            @Override
            public void run() {
                listener.onStarting();
            }
        });
    }

    private static void dispatchRunning(final StatusListener listener) {
        if (listener == null) {
            return;
        }
        MAIN_HANDLER.post(new Runnable() {
            @Override
            public void run() {
                listener.onRunning();
            }
        });
    }

    private static void dispatchStopped(final StatusListener listener) {
        if (listener == null) {
            return;
        }
        MAIN_HANDLER.post(new Runnable() {
            @Override
            public void run() {
                listener.onStopped();
            }
        });
    }

    private static void dispatchFailed(final StatusListener listener, final String message) {
        if (listener == null) {
            return;
        }
        MAIN_HANDLER.post(new Runnable() {
            @Override
            public void run() {
                listener.onFailed(message);
            }
        });
    }

    private static void dispatchLatency(final Attempt attempt, final StatusListener listener) {
        if (listener == null) {
            return;
        }
        MAIN_HANDLER.post(new Runnable() {
            @Override
            public void run() {
                synchronized (LOCK) {
                    if (activeAttempt != attempt || attempt.failed || state != State.RUNNING
                            || attempt.listener != listener) {
                        return;
                    }
                }
                listener.onLatencyChanged();
            }
        });
    }

    private static final class Attempt {
        private final long id;
        private final RelayConfig.Values values;
        private final RelayConfig.Values previous;
        private final boolean restorePrevious;
        private final boolean recovery;
        private StatusListener listener;
        private Listener http;
        private Listener game;
        private ScheduledExecutorService latencyExecutor;
        private long backendLatencyMs = -1L;
        private long gameLatencyMs = -1L;
        private boolean backendLatencyMeasured;
        private boolean gameLatencyMeasured;
        private int boundCount;
        private boolean failed;

        Attempt(long id, RelayConfig.Values values, RelayConfig.Values previous,
                boolean restorePrevious, boolean recovery, StatusListener listener) {
            this.id = id;
            this.values = values;
            this.previous = previous;
            this.restorePrevious = restorePrevious;
            this.recovery = recovery;
            this.listener = listener;
        }
    }

    private static final class Listener implements Runnable {
        private final Attempt attempt;
        private final String name;
        private final int localPort;
        private final String targetHost;
        private final int targetPort;
        private volatile boolean closed;
        private volatile ServerSocket serverSocket;
        private boolean bound;

        Listener(Attempt attempt, String name, int localPort, String targetHost, int targetPort) {
            this.attempt = attempt;
            this.name = name;
            this.localPort = localPort;
            this.targetHost = targetHost;
            this.targetPort = targetPort;
        }

        boolean isListening() {
            ServerSocket socket = serverSocket;
            return socket != null && !socket.isClosed();
        }

        @Override
        public void run() {
            try {
                Log.i(TAG, name + " listener starting: local=127.0.0.1:" + localPort
                        + " upstream=" + targetHost + ":" + targetPort);
                if (targetHost == null || targetHost.trim().isEmpty()) {
                    throw new IOException(name + " target host is empty");
                }
                if (targetPort < 1 || targetPort > 65535) {
                    throw new IOException(name + " target port is invalid");
                }
                if ("127.0.0.1".equals(targetHost) && localPort == targetPort) {
                    throw new IOException(name + " target would loop back");
                }
                ServerSocket socket = new ServerSocket();
                socket.setReuseAddress(true);
                socket.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), localPort));
                serverSocket = socket;
                Log.i(TAG, name + " listener bound on 127.0.0.1:" + localPort);
                listenerBound(this);
                while (!closed) {
                    Socket client = socket.accept();
                    Log.i(TAG, name + " accepted client=" + client.getRemoteSocketAddress());
                    ExecutorService pool = executor;
                    if (pool != null) {
                        pool.execute(new Bridge(name, client, targetHost, targetPort));
                    } else {
                        client.close();
                    }
                }
            } catch (Exception error) {
                if (!closed) {
                    String message = name + " 监听失败：" + error.getMessage();
                    Log.e(TAG, message, error);
                    listenerFailed(this, message);
                }
            } finally {
                Log.i(TAG, name + " listener stopped");
                close();
            }
        }

        void close() {
            closed = true;
            ServerSocket socket = serverSocket;
            if (socket != null) {
                try {
                    socket.close();
                } catch (IOException ignored) {
                }
            }
        }
    }

    private static final class Bridge implements Runnable {
        private final String name;
        private final Socket client;
        private final String targetHost;
        private final int targetPort;

        Bridge(String name, Socket client, String targetHost, int targetPort) {
            this.name = name;
            this.client = client;
            this.targetHost = targetHost;
            this.targetPort = targetPort;
        }

        @Override
        public void run() {
            Socket upstream = new Socket();
            long startedAt = System.currentTimeMillis();
            Log.i(TAG, name + " bridge starting client=" + client.getRemoteSocketAddress()
                    + " target=" + targetHost + ":" + targetPort);
            try {
                client.setTcpNoDelay(true);
                upstream.setTcpNoDelay(true);
                upstream.connect(new InetSocketAddress(targetHost, targetPort), 8000);
                Log.i(TAG, name + " upstream connected target=" + targetHost + ":" + targetPort);
                Thread down = new Thread(new Pipe(name + " down", upstream, client), TAG + "-down");
                Thread up = new Thread(new Pipe(name + " up", client, upstream), TAG + "-up");
                down.start();
                up.start();
                down.join();
                up.join();
            } catch (Exception error) {
                if (!client.isClosed()) {
                    lastError = name + " connection " + error.getMessage();
                    Log.w(TAG, lastError + " client=" + client.getRemoteSocketAddress()
                            + " target=" + targetHost + ":" + targetPort, error);
                }
            } finally {
                close(client);
                close(upstream);
                Log.i(TAG, name + " bridge stopped durationMs="
                        + (System.currentTimeMillis() - startedAt));
            }
        }
    }

    private static final class Pipe implements Runnable {
        private final String name;
        private final Socket source;
        private final Socket destination;

        Pipe(String name, Socket source, Socket destination) {
            this.name = name;
            this.source = source;
            this.destination = destination;
        }

        @Override
        public void run() {
            long totalBytes = 0L;
            long startedAt = System.currentTimeMillis();
            try {
                InputStream input = source.getInputStream();
                OutputStream output = destination.getOutputStream();
                byte[] buffer = new byte[16384];
                int count;
                while ((count = input.read(buffer)) != -1) {
                    output.write(buffer, 0, count);
                    output.flush();
                    totalBytes += count;
                }
            } catch (IOException error) {
                if (!source.isClosed() && !destination.isClosed()) {
                    Log.d(TAG, name + " closed: " + error.getMessage());
                }
            } finally {
                Log.i(TAG, name + " finished bytes=" + totalBytes + " durationMs="
                        + (System.currentTimeMillis() - startedAt));
                close(source);
                close(destination);
            }
        }
    }

    private static void close(Socket socket) {
        if (socket != null) {
            try {
                socket.close();
            } catch (IOException ignored) {
            }
        }
    }
}
