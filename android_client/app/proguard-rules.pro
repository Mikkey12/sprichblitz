# kotlinx.serialization — keep generated serializers for our @Serializable models.
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**

-keepclassmembers class io.github.mikkey12.sprichblitz.** {
    *** Companion;
}
-keepclasseswithmembers class io.github.mikkey12.sprichblitz.** {
    kotlinx.serialization.KSerializer serializer(...);
}
-if @kotlinx.serialization.Serializable class io.github.mikkey12.sprichblitz.**
-keep class io.github.mikkey12.sprichblitz.**$$serializer { *; }

# OkHttp / Okio ship their own consumer rules; nothing extra needed here.

# security-crypto pulls in Google Tink, which references Errorprone/JSR-305
# annotations that are compile-time only and absent at runtime. Harmless — tell
# R8 not to warn about them (otherwise minifyRelease fails on missing classes).
-dontwarn com.google.errorprone.annotations.**
-dontwarn javax.annotation.**
-dontwarn com.google.api.client.http.**
