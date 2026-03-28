# vim:set et sts=4 sw=4:
#
# ibus-stt - Speech To Text engine for IBus
# Copyright (C) 2022 Philippe Rouquier <bonfire-app@wanadoo.fr>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import logging
import threading

import numpy as np

from gi.repository import Gst, GLib, Gio

from sttgstbase import STTGstBase
from sttcurrentlocale import stt_current_locale

LOG_MSG=logging.getLogger()

class STTGstWhisper(STTGstBase):
    __gtype_name__ = 'STTGstWhisper'

    _pipeline_def="pulsesrc blocksize=3200 buffer-time=9223372036854775807 ! " \
                  "audio/x-raw,format=S16LE,rate=16000,channels=1 ! " \
                  "webrtcdsp noise-suppression-level=3 echo-cancel=false ! " \
                  "appsink name=WhisperSink emit-signals=true sync=false"

    _pipeline_def_alt="pulsesrc blocksize=3200 buffer-time=9223372036854775807 ! " \
                      "audio/x-raw,format=S16LE,rate=16000,channels=1 ! " \
                      "appsink name=WhisperSink emit-signals=true sync=false"

    _SAMPLE_RATE = 16000
    _BYTES_PER_SAMPLE = 2
    _SILENCE_THRESHOLD = 500
    _SILENCE_DURATION_SECS = 1.0
    _MIN_SPEECH_SECS = 0.3
    _MAX_BUFFER_SECS = 30
    _PARTIAL_INTERVAL_MS = 2000

    def __init__(self, current_locale=None):
        plugin=Gst.Registry.get().find_plugin("webrtcdsp")
        if plugin is not None:
            super().__init__(pipeline_definition=STTGstWhisper._pipeline_def)
            LOG_MSG.debug("Whisper: using Webrtcdsp plugin")
        else:
            super().__init__(pipeline_definition=STTGstWhisper._pipeline_def_alt)
            LOG_MSG.debug("Whisper: not using Webrtcdsp plugin")

        if self.pipeline is None:
            LOG_MSG.error("Whisper: pipeline was not created")
            return

        self._appsink = self.pipeline.get_by_name("WhisperSink")
        if self._appsink is None:
            LOG_MSG.error("Whisper: no appsink element")
            return

        self._appsink_id = self._appsink.connect("new-sample", self._on_new_sample)

        if current_locale is None:
            self._current_locale = stt_current_locale()
        else:
            self._current_locale = current_locale

        self._locale_id = self._current_locale.connect("changed", self._locale_changed)

        self._settings = Gio.Settings.new("org.freedesktop.ibus.engine.stt")

        self._lock = threading.Lock()
        self._audio_buffer = bytearray()
        self._speech_started = False
        self._silence_samples = 0

        self._whisper_model = None
        self._model_loaded = False
        self._use_partial = True
        self._partial_timer_id = 0
        self._transcribing = False

        self._load_model()

    def __del__(self):
        LOG_MSG.info("Whisper __del__")
        super().__del__()

    def destroy(self):
        self._current_locale.disconnect(self._locale_id)
        self._locale_id = 0

        if self._partial_timer_id != 0:
            GLib.source_remove(self._partial_timer_id)
            self._partial_timer_id = 0

        if self._appsink is not None:
            self._appsink.disconnect(self._appsink_id)
            self._appsink_id = 0
            self._appsink = None

        LOG_MSG.info("Whisper.destroy() called")
        super().destroy()

    def _get_language(self):
        locale_str = self._current_locale.locale
        if locale_str:
            return locale_str[:2]
        return None

    def _get_model_size(self):
        model_size = self._settings.get_string("whisper-model-size")
        if model_size in (None, "", "None"):
            return "small"
        return model_size

    def _load_model(self):
        model_size = self._get_model_size()

        def _load():
            try:
                from faster_whisper import WhisperModel
                self._whisper_model = WhisperModel(
                    model_size, device="cpu", compute_type="int8"
                )
                self._model_loaded = True
                LOG_MSG.info("Whisper model '%s' loaded", model_size)
            except ImportError:
                LOG_MSG.error("faster-whisper is not installed. "
                              "Install with: pip install faster-whisper")
                self._model_loaded = False
            except Exception as e:
                LOG_MSG.error("Failed to load Whisper model: %s", e)
                self._model_loaded = False

            GLib.idle_add(self.emit, "model-changed")

        threading.Thread(target=_load, daemon=True).start()

    def _locale_changed(self, locale):
        self.emit("model-changed")

    def _on_new_sample(self, sink):
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK

        buf = sample.get_buffer()
        success, mapinfo = buf.map(Gst.MapFlags.READ)
        if not success:
            return Gst.FlowReturn.OK

        data = bytes(mapinfo.data)
        buf.unmap(mapinfo)

        audio_array = np.frombuffer(data, dtype=np.int16)
        rms = np.sqrt(np.mean(audio_array.astype(np.float32) ** 2))

        samples_in_chunk = len(data) // self._BYTES_PER_SAMPLE
        silence_limit = int(self._SILENCE_DURATION_SECS * self._SAMPLE_RATE)
        min_speech_bytes = int(self._MIN_SPEECH_SECS * self._SAMPLE_RATE * self._BYTES_PER_SAMPLE)
        max_buffer_bytes = int(self._MAX_BUFFER_SECS * self._SAMPLE_RATE * self._BYTES_PER_SAMPLE)

        transcribe_data = None

        with self._lock:
            if rms > self._SILENCE_THRESHOLD:
                self._speech_started = True
                self._silence_samples = 0
                self._audio_buffer.extend(data)
            elif self._speech_started:
                self._silence_samples += samples_in_chunk
                self._audio_buffer.extend(data)

                if self._silence_samples >= silence_limit:
                    if len(self._audio_buffer) >= min_speech_bytes:
                        transcribe_data = bytes(self._audio_buffer)
                    self._audio_buffer = bytearray()
                    self._speech_started = False
                    self._silence_samples = 0

            if len(self._audio_buffer) >= max_buffer_bytes:
                transcribe_data = bytes(self._audio_buffer)
                self._audio_buffer = bytearray()
                self._speech_started = False
                self._silence_samples = 0

        if transcribe_data is not None:
            GLib.idle_add(self._transcribe_async, transcribe_data, True)

        return Gst.FlowReturn.OK

    def _audio_to_float(self, audio_bytes):
        return np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    def _transcribe(self, audio_data, beam_size=5, vad_filter=True):
        if not self._model_loaded or self._whisper_model is None:
            return ""

        try:
            audio_float = self._audio_to_float(audio_data)
            language = self._get_language()
            segments, _ = self._whisper_model.transcribe(
                audio_float,
                language=language,
                beam_size=beam_size,
                vad_filter=vad_filter,
            )
            return " ".join(seg.text.strip() for seg in segments)
        except Exception as e:
            LOG_MSG.error("Whisper transcription error: %s", e)
            return ""

    def _transcribe_async(self, audio_data, is_final):
        if self._transcribing:
            return False

        self._transcribing = True

        def _work():
            text = self._transcribe(
                audio_data,
                beam_size=5 if is_final else 1,
                vad_filter=is_final,
            )
            self._transcribing = False
            if text:
                signal = "text" if is_final else "partial-text"
                GLib.idle_add(self.emit, signal, text)

        threading.Thread(target=_work, daemon=True).start()
        return False

    def _partial_tick(self):
        if not self._model_loaded or self._transcribing:
            return True

        with self._lock:
            if not self._speech_started or len(self._audio_buffer) == 0:
                return True
            audio_data = bytes(self._audio_buffer)

        min_bytes = int(self._MIN_SPEECH_SECS * self._SAMPLE_RATE * self._BYTES_PER_SAMPLE)
        if len(audio_data) < min_bytes:
            return True

        self._transcribe_async(audio_data, False)
        return True

    def _run_real(self):
        result = super()._run_real()
        if result and self._use_partial and self._partial_timer_id == 0:
            self._partial_timer_id = GLib.timeout_add(
                self._PARTIAL_INTERVAL_MS, self._partial_tick
            )
        return result

    def _stop_real(self):
        if self._partial_timer_id != 0:
            GLib.source_remove(self._partial_timer_id)
            self._partial_timer_id = 0
        return super()._stop_real()

    def get_final_results(self):
        with self._lock:
            if len(self._audio_buffer) == 0:
                return
            audio_data = bytes(self._audio_buffer)
            self._audio_buffer = bytearray()
            self._speech_started = False
            self._silence_samples = 0

        min_bytes = int(self._MIN_SPEECH_SECS * self._SAMPLE_RATE * self._BYTES_PER_SAMPLE)
        if len(audio_data) < min_bytes:
            return

        text = self._transcribe(audio_data)
        if text:
            self.emit("text", text)

    def set_use_partial_results(self, active):
        self._use_partial = active
        if not active and self._partial_timer_id != 0:
            GLib.source_remove(self._partial_timer_id)
            self._partial_timer_id = 0

    def set_alternatives_num(self, num):
        pass

    def has_model(self):
        if not self._model_loaded:
            return False
        return super().has_model()
