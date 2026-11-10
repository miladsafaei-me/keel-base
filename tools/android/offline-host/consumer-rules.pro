# The web app calls these by name through window.NativeApp.
-keepclassmembers class keel.offlinehost.Bridge {
    @android.webkit.JavascriptInterface <methods>;
}
-keepattributes JavascriptInterface
