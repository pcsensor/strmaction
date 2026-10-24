Playback, cache, network, trust core and app icons imported from pcsensor/strmaction-ios
at 40cb910e155b28f8c15ef0d2721d6f5b6c6a2ea6. Local changes fix zero-cache semantics,
settings integration and shared player adaptation.

The shared Flutter client compiles this core through ci/prepare_mobile.py and
client_flutter/platform/ios/UnifiedPlayerPlugin.swift. The original repository
retains the full native app and its history. No submodule or second checkout is
required. The standalone native CI baseline remains recoverable in commit 4eed5b6.
