import time
import struct
import os
import wave
import shutil
import subprocess
import fluidsynth
import threading

from pathlib import Path
import sys

FILE_PATH = Path(__file__).resolve()
PROJECT_ROOT = FILE_PATH.parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

# MidiRecorder handles all MIDI event recording, playback, and audio file export
# Supports simultaneous recording and playback, MIDI export, WAV rendering, and MP3 conversion
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
        
        # Export options: which file formats to save (MIDI, WAV, MP3)
        # separate_playback: if True, moves completed recordings to playbacks/ folder
        self.options = {
            "save_mid": True, "save_mp3": False, "save_wav": False, "separate_playback": False
        }

    # Configure which file formats to save after recording completes
    def set_options(self, options_dict):
        if options_dict:
            self.options.update(options_dict)

    # Set soundfont, bank, preset, and MIDI channel for the instrument to be recorded
    # is_drum=True sets channel to 9 (percussion), False uses channel 0 (melodic)
    def set_instrument(self, sf2_path, bank, preset, is_drum=False):
        self.sf2_path = sf2_path
        self.bank = bank
        self.preset = preset
        self.channel = 9 if is_drum else 0

    # Start recording MIDI events; resets event list and timer
    def start(self):
        self.is_recording = True
        self.start_time = time.time()
        self.events = []  # Clear previous events
        self.last_filename = None
        
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
        self.last_filename = filename 
        
        os.makedirs("recordings", exist_ok=True)
        midi_path = os.path.join("recordings", filename)
        
        # Write MIDI file immediately
        self._write_midi_file(midi_path)
        # Process WAV/MP3 export in background thread to avoid blocking UI
        threading.Thread(target=self._process_files, args=(filename, midi_path)).start()

    # Background thread target: renders WAV from MIDI if needed, converts to MP3, manages file cleanup
    # Respects options for which formats to keep (save_mid, save_wav, save_mp3)
    def _process_files(self, filename, midi_path):
        wav_path = midi_path.replace(".mid", ".wav")
        mp3_path = midi_path.replace(".mid", ".mp3")
        
        # Only render audio if WAV or MP3 export is requested
        need_audio = self.options["save_wav"] or self.options["save_mp3"]
        
        if need_audio:
            if self.sf2_path and os.path.exists(self.sf2_path):
                print(">>> Renderizando WAV...")
                self._render_to_wav(wav_path)  # FluidSynth rendering to WAV
                
                if self.options["save_mp3"]:
                    print(">>> Convertendo para MP3...")
                    self._convert_wav_to_mp3(wav_path)  # FFmpeg conversion
            else:
                print(">>> AVISO: SF2 não encontrado.")

        time.sleep(0.5) 
        
        # Delete unwanted file formats based on options
        if not self.options["save_mid"]:
            try: os.remove(midi_path); print(">>> MIDI excluído.")
            except: pass
            
        if not self.options["save_wav"] and os.path.exists(wav_path):
            try: os.remove(wav_path); print(">>> WAV excluído.")
            except: pass

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
        # Wait for playback thread to finish (with 0.5s timeout)
        if self.playback_thread and self.playback_thread.is_alive():
            self.playback_thread.join(timeout=0.5)
            
        # Send MIDI panic to stop all sounding notes
        if self.cached_fs:
            try:
                self.cached_fs.cc(self.channel, 123, 0)  # All Notes Off
                self.cached_fs.cc(self.channel, 120, 0)  # All Sound Off
            except: pass
            
        print(">>> Playback parado.")

    # Start background playback loop of last_recording; can play while recording new notes simultaneously
    def start_playback(self, fs_instance):
        if not self.last_recording:
            print(">>> Nenhuma gravação para tocar.")
            return
            
        # Store FluidSynth instance for event playback in background thread
        self.cached_fs = fs_instance 
        
        # Optionally move recordings to playbacks/ folder for organization
        if self.options["separate_playback"] and self.last_filename:
            self._move_to_playbacks()

        print(">>> Iniciando Loop...")
        self.is_playing = True
        # Spawn daemon thread to loop playback of recorded MIDI events
        self.playback_thread = threading.Thread(target=self._playback_loop, args=(fs_instance, True))
        self.playback_thread.daemon = True
        self.playback_thread.start()

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
                    evt = self.last_recording[evt_idx]
                    
                    # Trigger note-on at output and inject into current recording if active
                    if evt["type"] == "on": 
                        fs.noteon(self.channel, evt["note"], evt["vel"])
                        if self.is_recording:
                            self.record_note_on(evt["note"], evt["vel"])  # Overdub: add to recording
                            
                    # Trigger note-off at output and inject into current recording if active
                    elif evt["type"] == "off": 
                        fs.noteoff(self.channel, evt["note"])
                        if self.is_recording:
                            self.record_note_off(evt["note"])  # Overdub: add to recording

                    # Replay Control Change events (e.g., modulation, volume) with overdub support
                    elif evt["type"] == "cc":
                        fs.cc(self.channel, evt["controller"], evt["value"])
                        if self.is_recording:
                            self.record_cc(self.channel, evt["controller"], evt["value"])  # Overdub: add to recording
                            
                    evt_idx += 1
                time.sleep(0.002)  # Small sleep to prevent busy-waiting
            
            # Exit if not looping
            if not loop:
                self.is_playing = False
                break
                
            # Wait for loop to complete before restarting
            while self.is_playing and (time.time() - loop_start) < total_duration:
                time.sleep(0.05)
        
        # Cleanup: send All Notes Off to stop any lingering notes
        if self.cached_fs:
            self.cached_fs.cc(self.channel, 123, 0)

    # Move completed recording files (MIDI, WAV, MP3) from recordings/ to playbacks/ folder
    def _move_to_playbacks(self):
        try:
            os.makedirs("playbacks", exist_ok=True)
            base_name = self.last_filename.replace(".mid", "")
            exts = [".mid", ".wav", ".mp3"]  # All possible export formats
            moved = False
            for ext in exts:
                src = os.path.join("recordings", base_name + ext)
                dst = os.path.join("playbacks", base_name + ext)
                if os.path.exists(src):
                    shutil.move(src, dst)
                    moved = True
            if moved:
                print(f">>> Movido para 'playbacks'.")
                self.last_filename = None 
        except Exception as e:
            print(f"Erro mover: {e}")

    # Record MIDI Note On event with relative timestamp
    def record_note_on(self, note, velocity=127):
        if not self.is_recording: return
        timestamp = time.time() - self.start_time
        self.events.append({"time": timestamp, "type": "on", "note": note, "vel": velocity})

    # Record MIDI Note Off event with relative timestamp
    def record_note_off(self, note):
        if not self.is_recording: return
        timestamp = time.time() - self.start_time
        self.events.append({"time": timestamp, "type": "off", "note": note, "vel": 0})

    # Record MIDI Control Change event (e.g., volume, modulation, pan) with relative timestamp
    def record_cc(self, channel, controller, value):
        if not self.is_recording: return
        timestamp = time.time() - self.start_time
        self.events.append({"time": timestamp, "type": "cc", "controller": controller, "value": value})

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
            
            if evt["type"] == "on":
                # Note On: status byte + note + velocity
                status = 0x90 | self.channel
                track_data += struct.pack('BB', status, evt["note"])
                track_data += struct.pack('B', evt["vel"])
            elif evt["type"] == "off":
                # Note Off: status byte + note + velocity (0)
                status = 0x80 | self.channel
                track_data += struct.pack('BB', status, evt["note"])
                track_data += struct.pack('B', 0)
            elif evt["type"] == "cc":
                # Control Change: status byte + controller number + value
                status = 0xB0 | self.channel
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

    # Convert WAV file to MP3 using FFmpeg (192 kbps bitrate); deletes WAV after conversion
    def _convert_wav_to_mp3(self, wav_path):
        mp3_path = wav_path.replace(".wav", ".mp3")
        try:
            # Use FFmpeg to encode: input WAV -> MP3 with 192k bitrate
            subprocess.run(['ffmpeg', '-y', '-i', wav_path, '-b:a', '192k', mp3_path], 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            # Clean up WAV file
            try: os.remove(wav_path) 
            except: pass
        except: print("FFmpeg não encontrado.")