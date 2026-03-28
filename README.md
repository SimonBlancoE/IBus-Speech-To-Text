# IBus Speech To Text Input Method
A speech to text IBus Input Method using VOSK or Whisper, written in Python. When enabled, you can dictate text to any application supporting IBus (most if not all applications do).

Description
============

This Input Method uses VOSK (https://github.com/alphacep/VOSK-api) or Whisper (via faster-whisper) for voice recognition and allows to dictate text in several languages in any application that supports IBus.
One of the main advantages is that both backends perform voice recognition locally and do not rely on an online service.

It works on Wayland and likely Xorg, though it has not been tested with the latter.

Since it uses IBus, it should work with most if not all applications since most modern toolkits (GTK, QT) all support IBus.

It has been tested with French, English and Spanish but it should support all languages for which a voice recognition model is available on this page : https://alphacephei.com/VOSK/models

Note: you do not need to install the model manually, the setup tool can do it for you and lets you choose the model you want for your language (larger models tend to be more accurate of course but can require a lot of memory).

When there is a formatting file provided, IBus STT auto-formats the text that VOSK outputs (mainly adding spaces and capital letters when needed). Currently, such a file is provided for French, American English and Spanish (es_ES) but you can send me a new file for your language so I can integrate it (see the examples in data/formatting in the tree).

This file also adds support for voice commands to manage case, punctuation and diacritics.
For example, saying "capital letter california" yields "California" as a result and "comma" adds ",".

There is also a couple of possible voice commands, to switch between various modes (spelling, no formatting) or cancel dictated text.

All these commands can be configured and you can add new utterances to trigger a command.

You can add your own "voice shortcuts" for any language so that, for example, saying "write signature" yields:
"Best wishes,
John Doe"

See the setup tool.

Finally, if your language is supported, IBus STT can format numbers as digits. French, English and Spanish were tested but it should work with more languages (see the examples in data/numbers in the tree).

Dependencies
============

- meson > 0.59.0
- python 3.5.0
- babel (https://pypi.org/project/Babel/) which is probably packaged by your distribution
- ibus > 1.5.0 (the higher the better, it was tested with 1.5.26)
- Gio
- Gstreamer 1.20

The setup dialog depends on:
- libadwaita 1.1.0
- Gtk 4

For the VOSK backend (default), you also need gst-VOSK installed (https://github.com/PhilippeRo/gst-VOSK/).

For the Whisper backend, you need:
- faster-whisper (https://github.com/SYSTRAN/faster-whisper): `pip install faster-whisper`
- numpy: `pip install numpy` (usually installed as a dependency of faster-whisper)

Building
============

To install it in /usr (where most distributions install IBus):
```
  meson setup builddir --prefix=/usr
  cd builddir
  meson compile
  meson install
```

Usage
============

Activate the Input Method through the IBus menu (that depends on your desktop) and start speaking.
It might seem obvious but the quality of the microphone used largely influences the accuracy of the voice recognition.

This Input Method can also be enabled and disabled with the default shorcut ("Win + Space") used to switch between IBus Input Methods. By default, when IBus STT is enabled, voice recognition is not started immediately but there is a setting to change this behaviour. If enabled, you can start and stop voice recognition with the above shortcut.

Choosing a backend
============

By default, IBus STT uses the VOSK backend. To switch to the Whisper backend:

```
  gsettings set org.freedesktop.ibus.engine.stt stt-backend 'whisper'
```

To switch back to VOSK:
```
  gsettings set org.freedesktop.ibus.engine.stt stt-backend 'vosk'
```

You can also choose the Whisper model size (tiny, base, small, medium, large-v2, large-v3). Larger models are more accurate but require more memory and processing time:
```
  gsettings set org.freedesktop.ibus.engine.stt whisper-model-size 'base'
```

Note: after changing the backend or model size, you need to restart IBus (`ibus restart`) for the change to take effect. The Whisper model is downloaded automatically on first use.
