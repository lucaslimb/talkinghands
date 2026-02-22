import time
import struct
import os
import wave
import shutil
import threading
import pygame
from array import array
from datetime import datetime
import re

from pathlib import Path
import sys

FILE_PATH = Path(__file__).resolve()
PROJECT_ROOT = FILE_PATH.parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

# Configure FluidSynth path BEFORE importing fluidsynth
def _setup_fluidsynth_path():
    """Ensure FluidSynth DLL is in PATH before importing the module"""
    try:
        # Try to get the bundled FluidSynth path
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            project_root = Path(sys._MEIPASS)
        else:
            current_file = Path(__file__).resolve()
            project_root = current_file.parent.parent.parent
        
        fluidsynth_bin = project_root / "assets" / "fluidsynth-v2.5.1" / "bin"
        
        if fluidsynth_bin.exists():
            bin_str = str(fluidsynth_bin)
            current_path = os.environ.get("PATH", "")
            
            # Add to PATH at the beginning (highest priority)
            if bin_str not in current_path:
                os.environ["PATH"] = f"{bin_str};{current_path}"
            
            # Set environment variables for pyfluidsynth
            os.environ["FLUIDSYNTH_PATH"] = bin_str
    except Exception as e:
        print(f"[!] Warning: Could not pre-configure FluidSynth path in recorder: {e}")

# Call before importing fluidsynth
_setup_fluidsynth_path()

import fluidsynth
try:
    import mido
except Exception:
    mido = None

from src.config import settings

# MidiRecorder handles all MIDI event recording, playback, and audio file export
# Supports simultaneous recording and playback, MIDI export, and WAV rendering
class MidiRecorder:
    def __init__(self):
        # Recording state tracking
        self.is_recording = False
        self.start_time = 0
        self.events = []  # List of MIDI events recorded in real-time
        
        # Instrument configuration (soundfont bank/preset and MIDI channel)
        self.sf2_path = None
        self.bank = 0
        self.preset = 0
        self.channel = 0  # Channel 9 for drums, 0-15 for instruments
        
        # Playback management
        self.last_recording = []  # Copy of events used for playback looping
        self.last_filename = None 
        self.is_playing = False  # Playback loop active flag
        self.playback_thread = None  # Background thread for playback loop
        self.cached_fs = None  # FluidSynth instance reference for playback
        self._warned_missing_mido = False
        self.instrument_name = "Instrument"

        self.recordings_root = Path(getattr(settings, "RECORDINGS_ROOT", PROJECT_ROOT / "recordings"))
        self.mids_dir = Path(getattr(settings, "MIDS_DIR", self.recordings_root / "mids"))
        self.wav_dir = Path(getattr(settings, "WAV_DIR", self.recordings_root / "wav"))
        self.last_midi_pointer_path = self.recordings_root / ".last_midi_path"
        self.last_audio_pointer_path = self.recordings_root / ".last_audio_path"
        self.recordings_root.mkdir(parents=True, exist_ok=True)
        self.mids_dir.mkdir(parents=True, exist_ok=True)
        self.wav_dir.mkdir(parents=True, exist_ok=True)
        self.last_audio_path = None
        self.recording_playback_audio_path = None
        self.recording_had_playback_audio = False
        
        # Export options: gravação simplificada (MID + WAV sempre ativos)
        self.options = {
            "save_mid": True, "save_wav": True
        }

        self._bootstrap_last_recording_from_disk()

    # Configure which file formats to save after recording completes
    def set_options(self, options_dict):
        self.options = {"save_mid": True, "save_wav": True}

    def set_instrument_name(self, instrument_name):
        if instrument_name:
            self.instrument_name = str(instrument_name)

    def _slug(self, text):
        clean = re.sub(r"[^a-zA-Z0-9]+", "_", str(text)).strip("_")
        return clean or "instrument"

    def _strip_datetime_suffix(self, stem):
        return re.sub(r"_\d{8}_\d{4}$", "", str(stem))

    def _build_recording_stem(self):
        date_part = datetime.now().strftime("%d%m%Y_%H%M")
        current_name = self._slug(self.instrument_name)

        if self.recording_had_playback_audio and self.recording_playback_audio_path:
            previous_stem = Path(self.recording_playback_audio_path).stem
            previous_stem = self._strip_datetime_suffix(previous_stem)
            previous_name = self._slug(previous_stem)
            return f"{current_name}_{previous_name}_{date_part}"
        return f"{current_name}_{date_part}"

    def _candidate_midi_dirs(self):
        folders = [self.mids_dir]
        unique = []
        seen = set()
        for folder in folders:
            try:
                key = str(folder.resolve())
            except Exception:
                key = str(folder)
            if key in seen:
                continue
            seen.add(key)
            unique.append(folder)
        return unique

    def _find_latest_midi_path(self):
        latest = None
        latest_mtime = -1.0
        for folder in self._candidate_midi_dirs():
            if not folder.exists():
                continue
            for midi_path in folder.glob("*.mid"):
                try:
                    mtime = midi_path.stat().st_mtime
                    if mtime > latest_mtime:
                        latest_mtime = mtime
                        latest = midi_path
                except Exception:
                    continue
        return latest

    def _write_last_midi_pointer(self, midi_path):
        try:
            target = Path(midi_path).resolve()
            self.last_midi_pointer_path.write_text(str(target), encoding="utf-8")
        except Exception:
            pass

    def _write_last_audio_pointer(self, audio_path):
        try:
            target = Path(audio_path).resolve()
            self.last_audio_pointer_path.write_text(str(target), encoding="utf-8")
            self.last_audio_path = str(target)
        except Exception:
            pass

    def _read_last_midi_pointer(self):
        try:
            if not self.last_midi_pointer_path.exists():
                return None
            raw = self.last_midi_pointer_path.read_text(encoding="utf-8").strip()
            if not raw:
                return None
            path = Path(raw)
            if path.exists() and path.suffix.lower() == ".mid":
                return path
        except Exception:
            return None
        return None

    def _read_last_audio_pointer(self):
        try:
            if not self.last_audio_pointer_path.exists():
                return None
            raw = self.last_audio_pointer_path.read_text(encoding="utf-8").strip()
            if not raw:
                return None
            path = Path(raw)
            if path.exists() and path.suffix.lower() == ".wav":
                return path
        except Exception:
            return None
        return None

    def _cache_audio_path_for_filename(self, midi_filename):
        base_name = Path(midi_filename).stem
        return self.wav_dir / f"{base_name}.wav"

    def _resolve_audio_for_midi(self, midi_path):
        try:
            midi_name = Path(midi_path).name
            by_stem = self._cache_audio_path_for_filename(midi_name)
            if by_stem.exists():
                return by_stem

            legacy_next_to_midi = Path(midi_path).with_suffix(".wav")
            if legacy_next_to_midi.exists():
                return legacy_next_to_midi
        except Exception:
            return None
        return None

    def _bootstrap_last_recording_from_disk(self):
        audio_path = self._read_last_audio_pointer()
        if audio_path is not None:
            self.last_audio_path = str(audio_path)

        from_pointer = self._read_last_midi_pointer()
        if from_pointer is not None:
            if self._load_midi_events(from_pointer):
                if not self.last_audio_path:
                    resolved_audio = self._resolve_audio_for_midi(from_pointer)
                    if resolved_audio is not None:
                        self._write_last_audio_pointer(resolved_audio)
                return True

        latest = self._find_latest_midi_path()
        if latest is None:
            return False
        loaded = self._load_midi_events(latest)
        if loaded and not self.last_audio_path:
            resolved_audio = self._resolve_audio_for_midi(latest)
            if resolved_audio is not None:
                self._write_last_audio_pointer(resolved_audio)
        return loaded

    def _load_midi_events(self, midi_path):
        if mido is None:
            if not self._warned_missing_mido:
                print(">>> AVISO: pacote 'mido' indisponível; playback de último .mid global desativado.")
                self._warned_missing_mido = True
            return False

        try:
            mid = mido.MidiFile(str(midi_path))
            tempo = 500000
            total_seconds = 0.0
            loaded_events = []

            for msg in mido.merge_tracks(mid.tracks):
                if msg.time:
                    total_seconds += mido.tick2second(msg.time, mid.ticks_per_beat, tempo)

                if msg.type == "set_tempo":
                    tempo = msg.tempo
                    continue

                if msg.type == "note_on":
                    channel = int(getattr(msg, "channel", self.channel))
                    if msg.velocity > 0:
                        loaded_events.append({
                            "time": total_seconds,
                            "type": "on",
                            "note": int(msg.note),
                            "vel": int(msg.velocity),
                            "channel": channel,
                        })
                    else:
                        loaded_events.append({
                            "time": total_seconds,
                            "type": "off",
                            "note": int(msg.note),
                            "vel": 0,
                            "channel": channel,
                        })
                elif msg.type == "note_off":
                    channel = int(getattr(msg, "channel", self.channel))
                    loaded_events.append({
                        "time": total_seconds,
                        "type": "off",
                        "note": int(msg.note),
                        "vel": 0,
                        "channel": channel,
                    })
                elif msg.type == "control_change":
                    channel = int(getattr(msg, "channel", self.channel))
                    loaded_events.append({
                        "time": total_seconds,
                        "type": "cc",
                        "controller": int(msg.control),
                        "value": int(msg.value),
                        "channel": channel,
                    })

            loaded_events.sort(key=lambda evt: evt["time"])
            self.last_recording = loaded_events
            self.last_filename = Path(midi_path).name
            self._write_last_midi_pointer(midi_path)

            if loaded_events:
                print(f">>> Playback carregado do último MIDI: {self.last_filename}")
                return True

            return False
        except Exception as exc:
            print(f">>> AVISO: falha ao carregar MIDI '{midi_path}': {exc}")
            return False

    # Set soundfont, bank, preset, and MIDI channel for the instrument to be recorded
    # is_drum=True sets channel to 9 (percussion), False uses channel 0 (melodic)
    def set_instrument(self, sf2_path, bank, preset, is_drum=False, instrument_name=None):
        self.sf2_path = sf2_path
        self.bank = bank
        self.preset = preset
        self.channel = 9 if is_drum else 0
        if instrument_name:
            self.set_instrument_name(instrument_name)

    # Start recording MIDI events; resets event list and timer
    def start(self):
        self.is_recording = True
        self.start_time = time.time()
        self.events = []  # Clear previous events
        self.last_filename = None
        self.recording_playback_audio_path = None
        self.recording_had_playback_audio = False

        if self.is_playing:
            if self.last_audio_path and Path(self.last_audio_path).exists():
                self.recording_playback_audio_path = self.last_audio_path
                self.recording_had_playback_audio = True
            else:
                pointer_audio = self._read_last_audio_pointer()
                if pointer_audio is not None:
                    self.recording_playback_audio_path = str(pointer_audio)
                    self.recording_had_playback_audio = True
        
        state_msg = " (Com Playback)" if self.is_playing else ""
        print(f">>> GRAVAÇÃO INICIADA{state_msg}")

    # Stop recording and save to MIDI file; triggers background processing for audio export
    # self.events contains all recorded events (live + any playback-injected notes)
    def stop(self, filename="output.mid"):
        if not self.is_recording: return
        
        self.is_recording = False
        duration = time.time() - self.start_time
        print(f">>> GRAVAÇÃO FINALIZADA ({duration:.2f}s)")
        
        # Stop playback loop if active
        if self.is_playing:
            self.stop_playback()
        
        # Copy events to last_recording for playback use, maintaining time sort order
        self.last_recording = list(self.events)
        self.last_recording.sort(key=lambda x: x["time"])
        stem = self._build_recording_stem()
        filename = f"{stem}.mid"
        self.last_filename = filename 
        recording_events_snapshot = list(self.last_recording)
        had_playback_audio = bool(self.recording_had_playback_audio)
        playback_audio_for_mix = self.recording_playback_audio_path
        
        self.mids_dir.mkdir(parents=True, exist_ok=True)
        midi_path = str(self.mids_dir / filename)
        self.last_audio_path = str(self._cache_audio_path_for_filename(filename))
        
        # Write MIDI file immediately
        self._write_midi_file(midi_path)
        self._write_last_midi_pointer(midi_path)
        # Process WAV export in background thread to avoid blocking UI
        threading.Thread(
            target=self._process_files,
            args=(filename, midi_path, recording_events_snapshot, had_playback_audio, playback_audio_for_mix)
        ).start()

    # Background thread target: renders WAV final and cache files
    def _process_files(self, filename, midi_path, recording_events, had_playback_audio=False, playback_audio_for_mix=None):
        wav_path = midi_path.replace(".mid", ".wav")
        wav_path = str(self.wav_dir / f"{Path(filename).stem}.wav")
        cache_wav_path = str(self._cache_audio_path_for_filename(filename))
        live_wav_path = str(self.wav_dir / f"{Path(filename).stem}_live_tmp.wav")

        if self.sf2_path and os.path.exists(self.sf2_path):
            try:
                self._render_events_to_wav(live_wav_path, recording_events)

                mixed_ok = False
                if had_playback_audio and playback_audio_for_mix and os.path.exists(playback_audio_for_mix):
                    try:
                        print(">>> Mixando áudio ao vivo com playback...")
                        self._mix_wav_files(live_wav_path, playback_audio_for_mix, wav_path)
                        mixed_ok = True
                    except Exception as mix_error:
                        print(f">>> AVISO: falha ao mixar playback ({mix_error}). Salvando áudio ao vivo.")

                if not mixed_ok:
                    shutil.copyfile(live_wav_path, wav_path)

                shutil.copyfile(wav_path, cache_wav_path)
                self._write_last_audio_pointer(cache_wav_path)
                print(">>> WAV salvo.")
            except Exception as render_error:
                print(f">>> AVISO: falha no processamento de WAV ({render_error})")
            finally:
                if os.path.exists(live_wav_path):
                    try:
                        os.remove(live_wav_path)
                    except Exception:
                        pass
        else:
            print(">>> AVISO: SF2 não encontrado.")

        time.sleep(0.5) 
        
        # Formatos são sempre mantidos: MID em /mids e WAV em /wav

    # Toggle playback on/off; if playing, stop; if stopped, start
    def toggle_playback(self, fs_instance):
        if self.is_playing:
            self.stop_playback()
        else:
            self.start_playback(fs_instance)

    # Stop playback loop and send MIDI panic commands (All Notes Off, All Sound Off) to silence instruments
    def stop_playback(self):
        if not self.is_playing: return

        self.is_playing = False
        try:
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except Exception:
            pass
        # Wait for playback thread to finish (with 0.5s timeout)
        if self.playback_thread and self.playback_thread.is_alive():
            self.playback_thread.join(timeout=0.5)
            
        # Send MIDI panic to stop all sounding notes
        if self.cached_fs:
            try:
                for channel in range(16):
                    self.cached_fs.cc(channel, 123, 0)  # All Notes Off
                    self.cached_fs.cc(channel, 120, 0)  # All Sound Off
            except: pass
            
        print(">>> Playback parado.")

    # Start background playback loop of last_recording; can play while recording new notes simultaneously
    def start_playback(self, fs_instance):
        if not self.last_recording:
            self._bootstrap_last_recording_from_disk()

        if not self.last_recording:
            print(">>> Nenhuma gravação para tocar.")
            return
            
        # Store FluidSynth instance for event playback in background thread
        self.cached_fs = fs_instance 

        playback_audio = None
        if self.last_audio_path and Path(self.last_audio_path).exists():
            playback_audio = self.last_audio_path
        else:
            from_pointer = self._read_last_audio_pointer()
            if from_pointer is not None:
                playback_audio = str(from_pointer)
                self.last_audio_path = playback_audio

        if not playback_audio and self.last_filename:
            resolved_audio = self._resolve_audio_for_midi(self.last_filename)
            if resolved_audio is not None:
                self._write_last_audio_pointer(resolved_audio)
                playback_audio = str(resolved_audio)

        if not playback_audio:
            print(">>> AVISO: áudio de playback não encontrado para o último take. Grave novamente para gerar cache de áudio.")
            return

        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.load(playback_audio)
            pygame.mixer.music.play(loops=-1)
        except Exception as exc:
            print(f">>> AVISO: falha ao iniciar playback de áudio: {exc}")
            return

        # Se o playback foi iniciado após o início da gravação,
        # ainda assim deve entrar na mescla final do take.
        if self.is_recording:
            self.recording_playback_audio_path = playback_audio
            self.recording_had_playback_audio = True
        
        print(">>> Iniciando Loop...")
        self.is_playing = True
        self.playback_thread = None

    # Background playback loop: cycles through recorded events, triggering them at correct times via FluidSynth
    # If is_recording=True, injects playback notes into current recording, allowing overdubs
    def _playback_loop(self, fs, loop=True):
        if not self.last_recording: return
        
        # Calculate loop duration to allow silence between loop cycles
        total_duration = self.last_recording[-1]["time"] + 1.0 
        
        # Main loop: continuously replay recording until is_playing is False
        while self.is_playing:
            loop_start = time.time()
            evt_idx = 0
            num_events = len(self.last_recording)
            
            # Inner loop: play all events in order, timing them relative to loop_start
            while self.is_playing and evt_idx < num_events:
                now = time.time() - loop_start
                # Process all events whose scheduled time has arrived
                while evt_idx < num_events and self.last_recording[evt_idx]["time"] <= now:
                    # Playback é somente áudio; não injeta eventos no take atual.
                    evt_idx += 1
                time.sleep(0.002)  # Small sleep to prevent busy-waiting
            
            # Exit if not looping
            if not loop:
                self.is_playing = False
                break
                
            # Wait for loop to complete before restarting
            while self.is_playing and (time.time() - loop_start) < total_duration:
                time.sleep(0.05)
        
        # Sem saída por nota no synth durante playback (áudio via mixer)

    # Record MIDI Note On event with relative timestamp
    def record_note_on(self, note, velocity=127, channel=None):
        if not self.is_recording: return
        timestamp = time.time() - self.start_time
        event_channel = self.channel if channel is None else int(channel)
        self.events.append({"time": timestamp, "type": "on", "note": note, "vel": velocity, "channel": event_channel})

    # Record MIDI Note Off event with relative timestamp
    def record_note_off(self, note, channel=None):
        if not self.is_recording: return
        timestamp = time.time() - self.start_time
        event_channel = self.channel if channel is None else int(channel)
        self.events.append({"time": timestamp, "type": "off", "note": note, "vel": 0, "channel": event_channel})

    # Record MIDI Control Change event (e.g., volume, modulation, pan) with relative timestamp
    def record_cc(self, channel, controller, value):
        if not self.is_recording: return
        timestamp = time.time() - self.start_time
        self.events.append({"time": timestamp, "type": "cc", "controller": controller, "value": value, "channel": int(channel)})

    # Construct and write standard MIDI file (SMF) from recorded events
    # Includes bank/preset selection and handles Note On/Off and Control Change events
    def _write_midi_file(self, filename):
        self.events.sort(key=lambda x: x["time"])  # Ensure chronological order
        # MIDI header: format 0 (single track), 96 ticks per quarter note
        header = struct.pack('>4sLhhh', b'MThd', 6, 0, 1, 96)
        track_data = bytearray()
        
        # Tempo: 500ms per quarter note (120 BPM)
        track_data += b'\x00\xFF\x51\x03\x07\xA1\x20'
        # Bank select MSB and LSB (for soundfont bank selection)
        track_data += b'\x00' + struct.pack('BB', 0xB0 | self.channel, 0) + struct.pack('B', self.bank // 128)
        track_data += b'\x00' + struct.pack('BB', 0xB0 | self.channel, 32) + struct.pack('B', self.bank % 128)
        # Program change (instrument select)
        track_data += b'\x00' + struct.pack('BB', 0xC0 | self.channel, self.preset)
        
        # Convert relative event times to MIDI delta times (in ticks)
        last_tick = 0
        ticks_per_sec = 192  # Resolution for timing accuracy
        for evt in self.events:
            current_tick = int(evt["time"] * ticks_per_sec)
            delta = current_tick - last_tick
            last_tick = current_tick
            track_data += self._write_var_len(delta)  # Variable-length quantity for delta time
            evt_channel = int(evt.get("channel", self.channel))
            
            if evt["type"] == "on":
                # Note On: status byte + note + velocity
                status = 0x90 | evt_channel
                track_data += struct.pack('BB', status, evt["note"])
                track_data += struct.pack('B', evt["vel"])
            elif evt["type"] == "off":
                # Note Off: status byte + note + velocity (0)
                status = 0x80 | evt_channel
                track_data += struct.pack('BB', status, evt["note"])
                track_data += struct.pack('B', 0)
            elif evt["type"] == "cc":
                # Control Change: status byte + controller number + value
                status = 0xB0 | evt_channel
                track_data += struct.pack('BB', status, evt["controller"])
                track_data += struct.pack('B', evt["value"])

        # End of track marker
        track_data += b'\x00\xFF\x2F\x00' 
        # Track header: 'MTrk' + track length
        track_header = struct.pack('>4sL', b'MTrk', len(track_data))
        with open(filename, 'wb') as f:
            f.write(header + track_header + track_data)

    # Encode integer as MIDI variable-length quantity (1-4 bytes, with continuation bits)
    # Used for delta times and other variable-length MIDI values
    def _write_var_len(self, value):
        buf = value & 0x7F
        while (value := value >> 7):
            buf <<= 8
            buf |= ((value & 0x7F) | 0x80)
        data = bytearray()
        while True:
            data.append(buf & 0xFF)
            if not (buf & 0x80): break
            buf >>= 8
        return data

    def _render_events_to_wav(self, output_path, events_to_render):
        if not self.sf2_path or not os.path.exists(self.sf2_path):
            raise RuntimeError("SF2 não encontrado para renderização de áudio")

        fs = fluidsynth.Synth()
        sfid = fs.sfload(self.sf2_path)

        # Configura os canais usados no take
        channels = sorted({int(evt.get("channel", self.channel)) for evt in events_to_render})
        if not channels:
            channels = [self.channel]

        for channel in channels:
            fs.program_select(channel, sfid, self.bank, self.preset)

        sample_rate = 44100
        wav_file = wave.open(output_path, 'wb')
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)

        current_time = 0.0
        for evt in events_to_render:
            duration = evt["time"] - current_time
            if duration > 0:
                frames = int(duration * sample_rate)
                if frames > 0:
                    wav_file.writeframes(fs.get_samples(frames))

            channel = int(evt.get("channel", self.channel))
            if evt["type"] == "on":
                fs.noteon(channel, evt["note"], evt["vel"])
            elif evt["type"] == "off":
                fs.noteoff(channel, evt["note"])
            elif evt["type"] == "cc":
                fs.cc(channel, evt["controller"], evt["value"])

            current_time = evt["time"]

        wav_file.writeframes(fs.get_samples(int(sample_rate)))
        wav_file.close()
        fs.delete()

    def _mix_wav_files(self, live_wav_path, playback_wav_path, output_wav_path):
        with wave.open(live_wav_path, 'rb') as live_wav, wave.open(playback_wav_path, 'rb') as pb_wav:
            params_live = (live_wav.getnchannels(), live_wav.getsampwidth(), live_wav.getframerate())
            params_pb = (pb_wav.getnchannels(), pb_wav.getsampwidth(), pb_wav.getframerate())

            if params_live != params_pb:
                raise RuntimeError("Áudios incompatíveis para mixagem")

            channels, sample_width, sample_rate = params_live
            if sample_width != 2:
                raise RuntimeError("Formato de áudio não suportado para mixagem")

            live_frames = live_wav.readframes(live_wav.getnframes())
            pb_frames = pb_wav.readframes(pb_wav.getnframes())

        live_samples = array('h')
        live_samples.frombytes(live_frames)

        pb_samples = array('h')
        pb_samples.frombytes(pb_frames)

        max_len = max(len(live_samples), len(pb_samples))
        if len(live_samples) < max_len:
            live_samples.extend([0] * (max_len - len(live_samples)))
        if len(pb_samples) < max_len:
            pb_samples.extend([0] * (max_len - len(pb_samples)))

        mixed = array('h')
        mixed.extend([0] * max_len)

        for index in range(max_len):
            value = int((live_samples[index] * 0.7) + (pb_samples[index] * 0.7))
            if value > 32767:
                value = 32767
            elif value < -32768:
                value = -32768
            mixed[index] = value

        with wave.open(output_wav_path, 'wb') as out_wav:
            out_wav.setnchannels(channels)
            out_wav.setsampwidth(sample_width)
            out_wav.setframerate(sample_rate)
            out_wav.writeframes(mixed.tobytes())

    # Render recorded MIDI events to audio WAV file using FluidSynth synthesis
    # Plays events in sequence, filling gaps with synthesized audio samples
    def _render_to_wav(self, output_path):
        try:
            # Create FluidSynth synthesizer and load soundfont
            fs = fluidsynth.Synth()
            sfid = fs.sfload(self.sf2_path)
            fs.program_select(self.channel, sfid, self.bank, self.preset)
            
            # Setup WAV file: stereo, 16-bit, 44.1 kHz
            sample_rate = 44100
            wav_file = wave.open(output_path, 'wb')
            wav_file.setnchannels(2); wav_file.setsampwidth(2); wav_file.setframerate(sample_rate)
            
            # Process events: generate audio samples between notes, trigger MIDI events
            current_time = 0.0
            events_to_render = self.last_recording if self.last_recording else self.events
            for evt in events_to_render:
                # Fill audio gap before this event
                duration = evt["time"] - current_time
                if duration > 0:
                    frames = int(duration * sample_rate)
                    if frames > 0: wav_file.writeframes(fs.get_samples(frames))
                
                # Trigger MIDI event in synthesizer
                if evt["type"] == "on": 
                    fs.noteon(self.channel, evt["note"], evt["vel"])
                elif evt["type"] == "off": 
                    fs.noteoff(self.channel, evt["note"])
                elif evt["type"] == "cc":
                    fs.cc(self.channel, evt["controller"], evt["value"])
                    
                current_time = evt["time"]
            
            # Render final silence (1 second of tail)
            wav_file.writeframes(fs.get_samples(int(sample_rate)))
            wav_file.close(); fs.delete()
        except Exception as e: print(f"Erro render: {e}")

