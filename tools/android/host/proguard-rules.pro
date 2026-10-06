# The web shell calls these by name through window.SignalAndroid.
-keepclassmembers class keel.signalapp.MainActivity$Bridge {
    @android.webkit.JavascriptInterface <methods>;
}
-keepattributes JavascriptInterface
