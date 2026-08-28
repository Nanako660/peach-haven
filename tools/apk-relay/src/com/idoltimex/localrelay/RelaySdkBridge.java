package com.idoltimex.localrelay;

import android.app.Activity;
import android.graphics.Color;
import android.util.Log;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ImageView;
import android.widget.LinearLayout;

import java.lang.reflect.Method;

/** Connects the local Relay UI to the SDK floating menu without compiling against SDK internals. */
public final class RelaySdkBridge {
    private static final String TAG = "LocalRelaySdkBridge";
    private static final int FLOATING_EXPANDED_CONTAINER = 0x7f08021b;
    private static final int FLOATING_EXPANDED_CONTAINER_RIGHT = 0x7f08021c;
    private static final String LEFT_TAG = "localrelay.sdk.menu.left";
    private static final String RIGHT_TAG = "localrelay.sdk.menu.right";

    private RelaySdkBridge() {
    }

    public static void install(Object holder, final Activity activity) {
        if (holder == null || activity == null || activity.isFinishing() || activity.isDestroyed()) {
            return;
        }
        try {
            Method getView = holder.getClass().getMethod("getView", Integer.TYPE);
            View left = (View) getView.invoke(holder, FLOATING_EXPANDED_CONTAINER);
            View right = (View) getView.invoke(holder, FLOATING_EXPANDED_CONTAINER_RIGHT);
            addRelayAction(left, activity, LEFT_TAG, false);
            addRelayAction(right, activity, RIGHT_TAG, true);
        } catch (Throwable error) {
            Log.w(TAG, "failed to add Relay action to SDK menu", error);
        }
    }

    public static void hideSdkFloating() {
        invokeStatic("hideFloatingButton", new Class<?>[0]);
    }

    public static void showSdkFloating(Activity activity) {
        if (activity == null || activity.isFinishing() || activity.isDestroyed()) {
            return;
        }
        invokeStatic("showFloatingButton", new Class<?>[]{Activity.class}, activity);
    }

    private static void addRelayAction(View containerView, final Activity activity,
                                       String tag, boolean right) {
        if (!(containerView instanceof LinearLayout)) {
            return;
        }
        LinearLayout container = (LinearLayout) containerView;
        if (container.findViewWithTag(tag) != null) {
            return;
        }

        ImageView action = new ImageView(activity);
        action.setTag(tag);
        action.setContentDescription("转发配置");
        action.setImageResource(android.R.drawable.ic_menu_manage);
        action.setColorFilter(Color.WHITE);
        action.setPadding(dp(activity, 2), dp(activity, 2), dp(activity, 2), dp(activity, 2));
        action.setClickable(true);
        action.setFocusable(true);
        action.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                RelayOverlay.openConfiguration(activity);
            }
        });

        int gap = dp(activity, 12);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(dp(activity, 24), dp(activity, 24));
        if (right) {
            params.setMargins(gap, 0, 0, 0);
        } else {
            params.setMargins(gap, 0, 0, 0);
        }
        container.addView(action, params);
        Log.i(TAG, "Relay action added to SDK floating menu: " + tag);
    }

    private static int dp(Activity activity, int value) {
        return (int) (value * activity.getResources().getDisplayMetrics().density + 0.5f);
    }

    private static void invokeStatic(String methodName, Class<?>[] parameterTypes, Object... args) {
        try {
            Class<?> manager = Class.forName("com.charles.weblib.sdk.GameSdkManager");
            Method method = manager.getMethod(methodName, parameterTypes);
            method.invoke(null, args);
        } catch (Throwable error) {
            Log.w(TAG, "SDK floating call failed: " + methodName, error);
        }
    }
}
