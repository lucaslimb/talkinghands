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

class MidiRecorder:
    def __init__(self):
        self.is_recording = False
        self.start_time = 0
        self.events = [] 
        self.sf2_path = None
        self.bank = 0
        self.preset = 0
        self.channel = 0
        
        self.last_recording = []
        self.last_filename = None 
        self.is_playing = False
        self.playback_thread = None
        self.cached_fs = None 
        
        self.options = {
            "save_mid": True, "save_mp3": False, "save_wav": False, "separate_playback": False
        }

    def set_options(self, options_dict):
        if options_dict:
            self.options.update(options_dict)

    def set_instrument(self, sf2_path, bank, preset, is_drum=False):
        self.sf2_path = sf2_path
        self.bank = bank
        self.preset = preset
        self.channel = 9 if is_drum else 0

    def start(self):
        # Se já estiver tocando (Loop no CV2), continuamos tocando e gravamos por cima (Overdub).
        self.is_recording = True
        self.start_time = time.time()
        self.events = [] 
        self.last_filename = None
        
        state_msg = " (Com Playback)" if self.is_playing else ""
        print(f">>> GRAVAÇÃO INICIADA{state_msg}")

    def stop(self, filename="output.mid"):
        if not self.is_recording: return
        
        self.is_recording = False
        duration = time.time() - self.start_time
        print(f">>> GRAVAÇÃO FINALIZADA ({duration:.2f}s)")
        
        # Para o playback ao terminar de gravar
        if self.is_playing:
            self.stop_playback()
        
        # A lista self.events já contém TUDO (Ao vivo + Playback injetado)
        self.last_recording = list(self.events)
        self.last_recording.sort(key=lambda x: x["time"])
        self.last_filename = filename 
        
        os.makedirs("recordings", exist_ok=True)
        midi_path = os.path.join("recordings", filename)
        
        self._write_midi_file(midi_path)
        threading.Thread(target=self._process_files, args=(filename, midi_path)).start()

    def _process_files(self, filename, midi_path):
        wav_path = midi_path.replace(".mid", ".wav")
        mp3_path = midi_path.replace(".mid", ".mp3")
        
        need_audio = self.options["save_wav"] or self.options["save_mp3"]
        
        if need_audio:
            if self.sf2_path and os.path.exists(self.sf2_path):
                print(">>> Renderizando WAV...")
                self._render_to_wav(wav_path)
                
                if self.options["save_mp3"]:
                    print(">>> Convertendo para MP3...")
                    self._convert_wav_to_mp3(wav_path)
            else:
                print(">>> AVISO: SF2 não encontrado.")

        time.sleep(0.5) 
        
        if not self.options["save_mid"]:
            try: os.remove(midi_path); print(">>> MIDI excluído.")
            except: pass
            
        if not self.options["save_wav"] and os.path.exists(wav_path):
            try: os.remove(wav_path); print(">>> WAV excluído.")
            except: pass

    def toggle_playback(self, fs_instance):
        if self.is_playing:
            self.stop_playback()
        else:
            self.start_playback(fs_instance)

    def stop_playback(self):
        """Para o playback e envia Panic MIDI para cortar som"""
        if not self.is_playing: return

        self.is_playing = False
        if self.playback_thread and self.playback_thread.is_alive():
            self.playback_thread.join(timeout=0.5)
            
        # Envia All Notes Off para garantir silêncio imediato
        if self.cached_fs:
            try:
                self.cached_fs.cc(self.channel, 123, 0) # All Notes Off
                self.cached_fs.cc(self.channel, 120, 0) # All Sound Off
            except: pass
            
        print(">>> Playback parado.")

    def start_playback(self, fs_instance):
        if not self.last_recording:
            print(">>> Nenhuma gravação para tocar.")
            return
            
        self.cached_fs = fs_instance 
        
        if self.options["separate_playback"] and self.last_filename:
            self._move_to_playbacks()

        print(">>> Iniciando Loop...")
        self.is_playing = True
        self.playback_thread = threading.Thread(target=self._playback_loop, args=(fs_instance, True))
        self.playback_thread.daemon = True
        self.playback_thread.start()

    def _playback_loop(self, fs, loop=True):
        if not self.last_recording: return
        
        total_duration = self.last_recording[-1]["time"] + 1.0 
        
        while self.is_playing:
            loop_start = time.time()
            evt_idx = 0
            num_events = len(self.last_recording)
            
            while self.is_playing and evt_idx < num_events:
                now = time.time() - loop_start
                while evt_idx < num_events and self.last_recording[evt_idx]["time"] <= now:
                    evt = self.last_recording[evt_idx]
                    
                    if evt["type"] == "on": 
                        fs.noteon(self.channel, evt["note"], evt["vel"])
                        if self.is_recording:
                            self.record_note_on(evt["note"], evt["vel"])
                            
                    elif evt["type"] == "off": 
                        fs.noteoff(self.channel, evt["note"])
                        if self.is_recording:
                            self.record_note_off(evt["note"])

                    # --- [NOVO] Playback de CC ---
                    elif evt["type"] == "cc":
                        fs.cc(self.channel, evt["controller"], evt["value"])
                        if self.is_recording:
                            self.record_cc(self.channel, evt["controller"], evt["value"])
                            
                    evt_idx += 1
                time.sleep(0.002)
            
            if not loop:
                self.is_playing = False
                break
                
            while self.is_playing and (time.time() - loop_start) < total_duration:
                time.sleep(0.05)
        
        if self.cached_fs:
            self.cached_fs.cc(self.channel, 123, 0)

    def _move_to_playbacks(self):
        try:
            os.makedirs("playbacks", exist_ok=True)
            base_name = self.last_filename.replace(".mid", "")
            exts = [".mid", ".wav", ".mp3"]
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

    def record_note_on(self, note, velocity=127):
        if not self.is_recording: return
        timestamp = time.time() - self.start_time
        self.events.append({"time": timestamp, "type": "on", "note": note, "vel": velocity})

    def record_note_off(self, note):
        if not self.is_recording: return
        timestamp = time.time() - self.start_time
        self.events.append({"time": timestamp, "type": "off", "note": note, "vel": 0})

    # --- [NOVO] Gravar CC ---
    def record_cc(self, channel, controller, value):
        if not self.is_recording: return
        timestamp = time.time() - self.start_time
        # O argumento 'channel' é aceito para compatibilidade, mas o gravador usa self.channel internamente
        self.events.append({"time": timestamp, "type": "cc", "controller": controller, "value": value})

    def _write_midi_file(self, filename):
        self.events.sort(key=lambda x: x["time"])
        header = struct.pack('>4sLhhh', b'MThd', 6, 0, 1, 96)
        track_data = bytearray()
        track_data += b'\x00\xFF\x51\x03\x07\xA1\x20'
        track_data += b'\x00' + struct.pack('BB', 0xB0 | self.channel, 0) + struct.pack('B', self.bank // 128)
        track_data += b'\x00' + struct.pack('BB', 0xB0 | self.channel, 32) + struct.pack('B', self.bank % 128)
        track_data += b'\x00' + struct.pack('BB', 0xC0 | self.channel, self.preset)
        last_tick = 0
        ticks_per_sec = 192 
        for evt in self.events:
            current_tick = int(evt["time"] * ticks_per_sec)
            delta = current_tick - last_tick
            last_tick = current_tick
            track_data += self._write_var_len(delta)
            
            if evt["type"] == "on":
                status = 0x90 | self.channel
                track_data += struct.pack('BB', status, evt["note"])
                track_data += struct.pack('B', evt["vel"])
            elif evt["type"] == "off":
                status = 0x80 | self.channel
                track_data += struct.pack('BB', status, evt["note"])
                track_data += struct.pack('B', 0)
            elif evt["type"] == "cc":
                # [NOVO] Escrever CC no MIDI
                status = 0xB0 | self.channel
                track_data += struct.pack('BB', status, evt["controller"])
                track_data += struct.pack('B', evt["value"])

        track_data += b'\x00\xFF\x2F\x00' 
        track_header = struct.pack('>4sL', b'MTrk', len(track_data))
        with open(filename, 'wb') as f:
            f.write(header + track_header + track_data)

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

    def _render_to_wav(self, output_path):
        try:
            fs = fluidsynth.Synth()
            sfid = fs.sfload(self.sf2_path)
            fs.program_select(self.channel, sfid, self.bank, self.preset)
            sample_rate = 44100
            wav_file = wave.open(output_path, 'wb')
            wav_file.setnchannels(2); wav_file.setsampwidth(2); wav_file.setframerate(sample_rate)
            current_time = 0.0
            events_to_render = self.last_recording if self.last_recording else self.events
            for evt in events_to_render:
                duration = evt["time"] - current_time
                if duration > 0:
                    frames = int(duration * sample_rate)
                    if frames > 0: wav_file.writeframes(fs.get_samples(frames))
                
                if evt["type"] == "on": 
                    fs.noteon(self.channel, evt["note"], evt["vel"])
                elif evt["type"] == "off": 
                    fs.noteoff(self.channel, evt["note"])
                elif evt["type"] == "cc":
                    # [NOVO] Renderizar CC no WAV
                    fs.cc(self.channel, evt["controller"], evt["value"])
                    
                current_time = evt["time"]
            wav_file.writeframes(fs.get_samples(int(sample_rate)))
            wav_file.close(); fs.delete()
        except Exception as e: print(f"Erro render: {e}")

    def _convert_wav_to_mp3(self, wav_path):
        mp3_path = wav_path.replace(".wav", ".mp3")
        try:
            subprocess.run(['ffmpeg', '-y', '-i', wav_path, '-b:a', '192k', mp3_path], 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            try: os.remove(wav_path) 
            except: pass
        except: print("FFmpeg não encontrado.")