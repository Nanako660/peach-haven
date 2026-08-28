package com.idoltimex.localrelay;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.text.InputType;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

import java.lang.ref.WeakReference;

public final class RelayOverlay {
    private static final String TAG = "LocalRelayOverlay";
    private static final int COLOR_PRIMARY = Color.rgb(35, 166, 214);
    private static final int COLOR_TEXT_SECONDARY = Color.rgb(95, 95, 95);
    private static final int COLOR_DIVIDER = Color.rgb(225, 225, 225);
    private static WeakReference<Activity> activityRef;
    private static View handle;
    private static WeakReference<AlertDialog> dialogRef;

    private RelayOverlay() {
    }

    public static void install(final Activity activity) {
        if (handle != null) {
            Log.d(TAG, "install skipped: overlay already exists");
            return;
        }
        Log.i(TAG, "install overlay activity=" + activity.getClass().getName());
        activityRef = new WeakReference<Activity>(activity);
        TextView button = new TextView(activity);
        button.setText("转发");
        button.setTextColor(Color.WHITE);
        button.setTextSize(12.0f);
        button.setGravity(Gravity.CENTER);
        button.setPadding(dp(activity, 10), dp(activity, 4), dp(activity, 10), dp(activity, 4));
        button.setAlpha(0.9f);
        GradientDrawable background = new GradientDrawable();
        background.setColor(Color.rgb(32, 32, 32));
        background.setCornerRadius(dp(activity, 24));
        button.setBackground(background);
        button.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                Log.i(TAG, "overlay clicked; opening configuration dialog");
                openConfiguration(activity);
            }
        });
        int size = dp(activity, 56);
        FrameLayout.LayoutParams params = new FrameLayout.LayoutParams(size, size);
        params.gravity = Gravity.TOP | Gravity.RIGHT;
        params.setMargins(0, dp(activity, 18), dp(activity, 18), 0);
        button.setVisibility(View.GONE);
        activity.addContentView(button, params);
        handle = button;
        Log.i(TAG, "overlay installed; starting relay");
        RelayController.start(activity);
    }

    public static void uninstall(Activity activity) {
        Log.i(TAG, "uninstall overlay activity=" + activity.getClass().getName());
        AlertDialog dialog = dialogRef == null ? null : dialogRef.get();
        if (dialog != null && dialog.isShowing()) {
            dialog.dismiss();
        }
        if (handle != null && handle.getParent() instanceof ViewGroup) {
            ((ViewGroup) handle.getParent()).removeView(handle);
        }
        handle = null;
        RelayController.stop(activity);
        activityRef = null;
        dialogRef = null;
    }

    public static void openConfiguration(final Activity activity) {
        if (activity == null || activity.isFinishing() || activity.isDestroyed()) {
            Log.w(TAG, "configuration request ignored for finished activity");
            return;
        }
        AlertDialog existing = dialogRef == null ? null : dialogRef.get();
        if (existing != null && existing.isShowing()) {
            return;
        }
        RelaySdkBridge.hideSdkFloating();
        showDialog(activity, new Runnable() {
            @Override
            public void run() {
                RelaySdkBridge.showSdkFloating(activity);
            }
        });
    }

    private static void showDialog(final Activity activity, final Runnable afterDismiss) {
        Log.i(TAG, "configuration dialog opened: " + RelayConfig.describe(activity));

        final ConfigUi ui = new ConfigUi(activity);
        LinearLayout content = new LinearLayout(activity);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(activity, 18), dp(activity, 4), dp(activity, 18), dp(activity, 8));

        LinearLayout statusRow = new LinearLayout(activity);
        statusRow.setGravity(Gravity.TOP);
        TextView statusLabel = new TextView(activity);
        statusLabel.setText("状态");
        statusLabel.setTextColor(COLOR_TEXT_SECONDARY);
        statusLabel.setTextSize(13.0f);
        statusLabel.setGravity(Gravity.TOP);
        statusRow.addView(statusLabel, new LinearLayout.LayoutParams(dp(activity, 46), -2));
        ui.status = new TextView(activity);
        ui.status.setText(RelayController.getStatus());
        ui.status.setTextColor(COLOR_PRIMARY);
        ui.status.setTextSize(13.0f);
        ui.status.setGravity(Gravity.TOP);
        ui.status.setMinLines(5);
        ui.status.setMaxLines(6);
        statusRow.addView(ui.status, new LinearLayout.LayoutParams(0, -2, 1.0f));
        content.addView(statusRow, new LinearLayout.LayoutParams(-1, -2));

        ui.enabled = new Switch(activity);
        ui.enabled.setText("启用转发");
        ui.enabled.setTextSize(16.0f);
        ui.enabled.setChecked(RelayConfig.isEnabled(activity));
        content.addView(ui.enabled, new LinearLayout.LayoutParams(-1, dp(activity, 48)));

        addEndpointSection(content, activity, "账号管理后台", "本地监听 127.0.0.1:8080",
                RelayConfig.getBackendHost(activity), RelayConfig.getBackendPort(activity), true, ui);
        addEndpointSection(content, activity, "游戏服务端", "本地监听 127.0.0.1:21001",
                RelayConfig.getGameHost(activity), RelayConfig.getGamePort(activity), false, ui);

        MaxHeightScrollView scrollView = new MaxHeightScrollView(activity,
                (int) (activity.getResources().getDisplayMetrics().heightPixels * 0.68f));
        scrollView.setFillViewport(true);
        scrollView.addView(content, new ScrollView.LayoutParams(-1, -2));

        LinearLayout titleBar = new LinearLayout(activity);
        titleBar.setGravity(Gravity.CENTER_VERTICAL);
        titleBar.setPadding(dp(activity, 18), 0, dp(activity, 18), 0);
        TextView title = new TextView(activity);
        title.setText("Relay 本地连接配置");
        title.setTextColor(COLOR_PRIMARY);
        title.setTextSize(20.0f);
        title.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        titleBar.addView(title, new LinearLayout.LayoutParams(-1, dp(activity, 54)));

        final AlertDialog dialog = new AlertDialog.Builder(activity)
                .setCustomTitle(titleBar)
                .setView(scrollView)
                .create();
        ui.dialog = dialog;
        ui.listener = new RelayController.StatusListener() {
            @Override
            public void onStarting() {
                ui.setBusy(true);
                ui.setStatus(RelayController.getStatus(), COLOR_PRIMARY);
            }

            @Override
            public void onRunning() {
                boolean notify = ui.awaitingStart;
                ui.awaitingStart = false;
                ui.setBusy(false);
                String status = RelayController.getStatus();
                ui.setStatus(status, COLOR_PRIMARY);
                if (notify && !ui.disposed && dialog.isShowing()) {
                    Toast.makeText(activity,
                            status.contains("已恢复") ? status : "转发已启动", Toast.LENGTH_SHORT).show();
                }
            }

            @Override
            public void onStopped() {
                ui.awaitingStart = false;
                ui.setBusy(false);
                ui.setStatus(RelayController.getStatus(), COLOR_TEXT_SECONDARY);
            }

            @Override
            public void onFailed(String message) {
                boolean notify = ui.awaitingStart;
                ui.awaitingStart = false;
                ui.setBusy(false);
                ui.setStatus("启动失败：" + message, Color.rgb(190, 55, 55));
                if (notify && !ui.disposed && dialog.isShowing()) {
                    Toast.makeText(activity, "转发启动失败：" + message, Toast.LENGTH_LONG).show();
                }
            }

            @Override
            public void onLatencyChanged() {
                ui.setStatus(RelayController.getStatus(), COLOR_PRIMARY);
            }
        };
        dialogRef = new WeakReference<AlertDialog>(dialog);
        dialog.setButton(AlertDialog.BUTTON_NEGATIVE, "关闭", (DialogInterface.OnClickListener) null);
        dialog.setButton(AlertDialog.BUTTON_POSITIVE, "保存", (DialogInterface.OnClickListener) null);
        dialog.setCanceledOnTouchOutside(false);
        dialog.setOnShowListener(new DialogInterface.OnShowListener() {
            @Override
            public void onShow(DialogInterface ignored) {
                ui.saveButton = dialog.getButton(AlertDialog.BUTTON_POSITIVE);
                ui.closeButton = dialog.getButton(AlertDialog.BUTTON_NEGATIVE);
                ui.saveButton.setOnClickListener(new View.OnClickListener() {
                    @Override
                    public void onClick(View view) {
                        saveConfiguration(activity, ui);
                    }
                });
                ui.closeButton.setOnClickListener(new View.OnClickListener() {
                    @Override
                    public void onClick(View view) {
                        dialog.dismiss();
                    }
                });
                ui.setBusy(RelayController.getState() == RelayController.State.STARTING);
                RelayController.observe(ui.listener);
                Window window = dialog.getWindow();
                if (window != null) {
                    int width = (int) (activity.getResources().getDisplayMetrics().widthPixels * 0.92f);
                    window.setLayout(width, WindowManager.LayoutParams.WRAP_CONTENT);
                }
            }
        });
        dialog.setOnDismissListener(new DialogInterface.OnDismissListener() {
            @Override
            public void onDismiss(DialogInterface ignored) {
                ui.dispose();
                if (dialogRef != null && dialogRef.get() == dialog) {
                    dialogRef = null;
                }
                if (afterDismiss != null) {
                    afterDismiss.run();
                }
            }
        });
        dialog.show();
    }

    private static void saveConfiguration(final Activity activity, final ConfigUi ui) {
        try {
            String backend = clean(ui.backendHost.getText().toString());
            String game = clean(ui.gameHost.getText().toString());
            int backendPort = port(ui.backendPort.getText().toString());
            int gamePort = port(ui.gamePort.getText().toString());
            rejectLoop(backend, backendPort, RelayConfig.LOCAL_BACKEND_PORT);
            rejectLoop(game, gamePort, RelayConfig.LOCAL_GAME_PORT);
            RelayConfig.Values next = new RelayConfig.Values(ui.enabled.isChecked(), backend,
                    backendPort, game, gamePort);
            ui.awaitingStart = next.enabled;
            ui.setBusy(true);
            RelayController.restart(activity, next, ui.listener);
            Log.i(TAG, "configuration restart requested: enabled=" + next.enabled
                    + " backend=" + next.backendHost + ":" + next.backendPort
                    + " game=" + next.gameHost + ":" + next.gamePort);
        } catch (IllegalArgumentException error) {
            ui.setStatus(error.getMessage(), Color.rgb(190, 55, 55));
            Toast.makeText(activity, error.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    private static void addEndpointSection(LinearLayout content, Activity activity, String title,
            String localText, String host, int port, boolean backend, ConfigUi ui) {
        TextView section = new TextView(activity);
        section.setText(title);
        section.setTextColor(Color.rgb(50, 50, 50));
        section.setTextSize(15.0f);
        section.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        section.setPadding(0, dp(activity, 8), 0, dp(activity, 2));
        content.addView(section, new LinearLayout.LayoutParams(-1, -2));

        TextView local = new TextView(activity);
        local.setText(localText + "  ←  上游目标");
        local.setTextColor(COLOR_TEXT_SECONDARY);
        local.setTextSize(12.0f);
        content.addView(local, new LinearLayout.LayoutParams(-1, dp(activity, 26)));

        LinearLayout row = new LinearLayout(activity);
        row.setGravity(Gravity.CENTER_VERTICAL);
        EditText hostInput = input(activity, host, "目标主机或域名", false);
        EditText portInput = input(activity, String.valueOf(port), "端口", true);
        row.addView(hostInput, new LinearLayout.LayoutParams(0, dp(activity, 48), 1.0f));
        LinearLayout.LayoutParams portParams = new LinearLayout.LayoutParams(dp(activity, 94), dp(activity, 48));
        portParams.setMargins(dp(activity, 8), 0, 0, 0);
        row.addView(portInput, portParams);
        content.addView(row, new LinearLayout.LayoutParams(-1, dp(activity, 50)));
        View divider = new View(activity);
        divider.setBackgroundColor(COLOR_DIVIDER);
        content.addView(divider, new LinearLayout.LayoutParams(-1, dp(activity, 1)));

        if (backend) {
            ui.backendHost = hostInput;
            ui.backendPort = portInput;
        } else {
            ui.gameHost = hostInput;
            ui.gamePort = portInput;
        }
    }

    private static EditText input(Activity activity, String value, String hint, boolean port) {
        EditText view = new EditText(activity);
        view.setSingleLine(true);
        view.setText(value);
        view.setHint(hint);
        view.setTextSize(15.0f);
        view.setInputType(port ? InputType.TYPE_CLASS_NUMBER
                : InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        return view;
    }

    private static String clean(String value) {
        String result = value == null ? "" : value.trim();
        if (result.isEmpty()) {
            throw new IllegalArgumentException("地址不能为空");
        }
        return result;
    }

    private static int port(String value) {
        try {
            int result = Integer.parseInt(value.trim());
            if (result < 1 || result > 65535) {
                throw new NumberFormatException();
            }
            return result;
        } catch (NumberFormatException error) {
            throw new IllegalArgumentException("端口必须是 1-65535");
        }
    }

    private static void rejectLoop(String host, int port, int localPort) {
        if (("127.0.0.1".equals(host) || "localhost".equalsIgnoreCase(host)) && port == localPort) {
            throw new IllegalArgumentException("目标地址不能指向本机中继端口");
        }
    }

    private static int dp(Activity activity, int value) {
        return (int) (value * activity.getResources().getDisplayMetrics().density + 0.5f);
    }

    private static final class ConfigUi {
        private final Activity activity;
        private AlertDialog dialog;
        private Switch enabled;
        private EditText backendHost;
        private EditText backendPort;
        private EditText gameHost;
        private EditText gamePort;
        private TextView status;
        private Button saveButton;
        private Button closeButton;
        private RelayController.StatusListener listener;
        private boolean awaitingStart;
        private boolean disposed;

        ConfigUi(Activity activity) {
            this.activity = activity;
        }

        void setBusy(boolean busy) {
            if (enabled != null) {
                enabled.setEnabled(!busy);
            }
            if (backendHost != null) {
                backendHost.setEnabled(!busy);
                backendPort.setEnabled(!busy);
                gameHost.setEnabled(!busy);
                gamePort.setEnabled(!busy);
            }
            if (saveButton != null) {
                saveButton.setEnabled(!busy);
            }
            if (closeButton != null) {
                closeButton.setEnabled(true);
            }
        }

        void setStatus(String value, int color) {
            if (!disposed && status != null) {
                status.setText(value);
                status.setTextColor(color);
            }
        }

        void dispose() {
            disposed = true;
            RelayController.removeStatusListener(listener);
        }
    }

    private static final class MaxHeightScrollView extends ScrollView {
        private final int maxHeight;

        MaxHeightScrollView(Activity context, int maxHeight) {
            super(context);
            this.maxHeight = maxHeight;
        }

        @Override
        protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
            super.onMeasure(widthMeasureSpec, heightMeasureSpec);
            if (getMeasuredHeight() > maxHeight) {
                setMeasuredDimension(getMeasuredWidth(), maxHeight);
            }
        }
    }
}
