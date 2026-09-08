function getCookie(name) {
    const match = document.cookie.match(new RegExp("(^|;\\s*)" + name + "=([^;]*)"));
    return match ? decodeURIComponent(match[2]) : "";
}

function urlB64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(base64);
    return Uint8Array.from(raw, (char) => char.charCodeAt(0));
}

async function enablePushNotifications() {
    const status = document.getElementById("push-status");
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
        status.textContent = "Push is not supported by this browser.";
        return;
    }
    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
        status.textContent = "Notification permission was denied.";
        return;
    }
    try {
        const registration = await navigator.serviceWorker.ready;
        const applicationServerKey = urlB64ToUint8Array(
            document.body.dataset.vapidPublicKey
        );
        const subscription = await registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey,
        });
        const response = await fetch("/push/subscribe/", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": getCookie("csrftoken"),
            },
            body: JSON.stringify(subscription.toJSON()),
        });
        status.textContent = response.ok
            ? "Push notifications enabled."
            : "Could not save the subscription.";
    } catch (error) {
        status.textContent = "Could not enable push notifications.";
    }
}

document.addEventListener("DOMContentLoaded", function () {
    const button = document.getElementById("enable-push");
    if (button) {
        button.addEventListener("click", enablePushNotifications);
    }
});
