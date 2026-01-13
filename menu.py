import customtkinter as ctk
from importlib import import_module, reload
import sys
import os
import ctypes
import config.settings as settings  

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

try:
    myappid = 'talkinghands.instrument.gui.1.0'
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except:
    pass

class InstrumentSelector(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        if os.path.exists(resource_path("icon.ico")):
            self.iconbitmap(resource_path("icon.ico"))

        # --- ORGANIZAÇÃO DO CATÁLOGO ---
        # Adicionada chave 'Flauta'
        self.catalog = {"Teclado": [], "Bateria": [], "Flauta": []}
        
        # Separa os instrumentos com base na configuração do settings.py
        for name, data in settings.INSTRUMENTS.items():
            sf_key = data[0] 
            if sf_key == "drums":
                self.catalog["Bateria"].append(name)
            elif sf_key == "flute":
                self.catalog["Flauta"].append(name)
            else:
                self.catalog["Teclado"].append(name)
        
        self.current_type = "Teclado"
        # Lógica de fallback se não houver teclado
        if not self.catalog["Teclado"]:
            if self.catalog["Bateria"]: self.current_type = "Bateria"
            elif self.catalog["Flauta"]: self.current_type = "Flauta"
            
        self.instruments = self.catalog[self.current_type]
        self.current_index = 0
        self.selected_instrument = None
        self.selected_type = None
        
        self._load_defaults_from_settings()

        # Vars de Gravação
        def_mid = getattr(settings, 'RECORD_SAVE_MID', True)
        def_mp3 = getattr(settings, 'RECORD_SAVE_MP3', False)
        def_wav = getattr(settings, 'RECORD_SAVE_WAV', False)
        def_pb_folder = getattr(settings, 'RECORD_SEPARATE_PLAYBACK_FOLDER', False)

        self.var_mid = ctk.BooleanVar(value=def_mid)
        self.var_mp3 = ctk.BooleanVar(value=def_mp3)
        self.var_wav = ctk.BooleanVar(value=def_wav)
        self.var_separate_pb = ctk.BooleanVar(value=def_pb_folder)
        
        # Var Específica Flauta
        self.var_invert_blow = ctk.BooleanVar(value=False) # False = Boca fechada toca forte (Padrão sopro)

        self.is_advanced_open = False

        self.base_height = 250
        self.expanded_height = 600 # Aumentei um pouco para caber opções da flauta

        self.title("Talking Hands Launcher")
        self.geometry(f"600x{self.base_height}")
        self.resizable(False, False)
        self._center_window(600, self.base_height)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Frame Principal
        self.main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main_frame.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        self.main_frame.grid_columnconfigure(1, weight=1)
        self.main_frame.grid_rowconfigure((0, 1, 2), weight=0)

        # Segmented Button agora inclui Flauta
        self.seg_type = ctk.CTkSegmentedButton(
            self.main_frame,
            values=["Teclado", "Bateria", "Flauta"],
            command=self.change_instrument_type,
            font=("Segoe UI", 14, "bold"),
            height=35
        )
        self.seg_type.set(self.current_type)
        self.seg_type.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 20), padx=80)
        
        arrow_font = ("Segoe UI", 32, "bold")
        main_font = ("Segoe UI", 24, "bold")

        self.btn_prev = ctk.CTkButton(
            self.main_frame, text="❮", font=arrow_font, width=60, height=60, corner_radius=30,
            fg_color="#2b2b2b", hover_color="#404040", command=lambda: self.change_preset(-1)
        )
        self.btn_prev.grid(row=2, column=0, padx=(0, 20))

        start_text = self.instruments[0].upper() if self.instruments else "NENHUM"
        self.btn_start = ctk.CTkButton(
            self.main_frame, text=start_text, font=main_font,
            height=80, width=300, corner_radius=40,
            fg_color="#005bb0", hover_color="#003E90", text_color="white",
            command=self.confirm_selection
        )
        self.btn_start.grid(row=2, column=1, sticky="ew")

        self.btn_next = ctk.CTkButton(
            self.main_frame, text="❯", font=arrow_font, width=60, height=60, corner_radius=30,
            fg_color="#2b2b2b", hover_color="#404040", command=lambda: self.change_preset(1)
        )
        self.btn_next.grid(row=2, column=2, padx=(20, 0))

        # --- Botão Toggle Avançado ---
        self.btn_advanced = ctk.CTkButton(
            self.main_frame, text="Avançado ▼", font=("Consolas", 12),
            fg_color="transparent", border_width=1, border_color="#444444",
            text_color="#888888", hover_color="#333333", height=28, width=160,
            command=self.toggle_advanced
        )
        self.btn_advanced.grid(row=3, column=0, columnspan=3, sticky="n", pady=(15, 10))

        # --- Painel Avançado ---
        self.advanced_frame = ctk.CTkScrollableFrame(
            self.main_frame, 
            fg_color="#1a1a1a", 
            corner_radius=10,
            height=300,
        )

        self.bind("<Left>", lambda e: self.change_preset(-1))
        self.bind("<Right>", lambda e: self.change_preset(1))
        self.bind("<Return>", lambda e: self.confirm_selection())

    def _load_defaults_from_settings(self):
        # Keyboard / Drums defaults
        self.custom_sustain = float(getattr(settings, 'SUSTAIN_DECAY', 0.8))
        self.custom_lift = float(getattr(settings, 'LIFT_THRESHOLD', 0.02))
        self.custom_tolerance = float(getattr(settings, 'TOUCH_TOLERANCE', 0.005))
        self.custom_touch_velocity = float(getattr(settings, 'TOUCH_VELOCITY', 0.012))
        
        # Flute Defaults
        self.custom_mouth_peak = float(getattr(settings, 'MOUTH_PEAK_OPEN', 0.01))
        self.custom_mouth_max = float(getattr(settings, 'MOUTH_MAX_OPEN', 0.05))
        self.custom_hole_size = "Médio" # Valor visual inicial

        self.recordings_folder = str(getattr(settings, 'RECORDINGS_FOLDER', 'recordings'))

    def _center_window(self, width, height):
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = (screen_width / 2) - (width / 2)
        y = (screen_height / 2) - (height / 2)
        self.geometry(f'{width}x{height}+{int(x)}+{int(y)}')

    def change_instrument_type(self, value):
        self.current_type = value
        self.instruments = self.catalog[value]
        self.current_index = 0
        
        text = self.instruments[0].upper() if self.instruments else "NENHUM"
        self.btn_start.configure(text=text)
        
        if self.is_advanced_open:
            self._rebuild_advanced_panel()

    def change_preset(self, direction):
        if not self.instruments: return
        self.current_index = (self.current_index + direction) % len(self.instruments)
        self.btn_start.configure(text=self.instruments[self.current_index].upper())

    def toggle_advanced(self):
        if self.is_advanced_open:
            self.advanced_frame.grid_forget()
            self.btn_advanced.configure(text="Avançado ▼")
            self.geometry(f"600x{self.base_height}")
            self.is_advanced_open = False
        else:
            self._rebuild_advanced_panel()
            self.advanced_frame.grid(row=4, column=0, columnspan=3, sticky="ew", pady=0)
            self.btn_advanced.configure(text="Ocultar ▲")
            self.geometry(f"600x{self.expanded_height}")
            self.is_advanced_open = True

    def _clear_frame(self, frame):
        for widget in frame.winfo_children():
            widget.destroy()

    def _rebuild_advanced_panel(self):
        self._clear_frame(self.advanced_frame)
        
        if self.current_type == "Teclado":
            self._build_keyboard_options()
        elif self.current_type == "Bateria":
            self._build_drums_options()
        else:
            self._build_flute_options()
            
        ctk.CTkFrame(self.advanced_frame, height=1, fg_color="#333333").pack(fill="x", padx=40, pady=(15, 5))
        self.btn_reset = ctk.CTkButton(
            self.advanced_frame, text="Restaurar Padrões", font=("Segoe UI", 11),
            fg_color="transparent", border_width=1, border_color="#555555", 
            hover_color="#333333", text_color="#888888", 
            height=24, width=140,
            command=self.restore_defaults
        )
        self.btn_reset.pack(pady=(5, 15))

    # --- UI FLAUTA ---
    def _build_flute_options(self):
        frm = ctk.CTkFrame(self.advanced_frame, fg_color="transparent")
        frm.pack(fill="x", padx=10, pady=5)

        # Seção Sopro
        ctk.CTkLabel(frm, text="ÁUDIO", font=("Segoe UI", 12, "bold"), text_color="#005bb0", anchor="center").pack(fill="x")
        
        # Toggle Inverter
        self.chk_invert = ctk.CTkSwitch(frm, text="Inverter lógica de sopro", 
                                        variable=self.var_invert_blow, 
                                        onvalue=True, offvalue=False,
                                        font=("Segoe UI", 11), progress_color="#005bb0")
        self.chk_invert.pack(pady=(5, 10))
        ctk.CTkLabel(frm, text="Padrão: quanto mais fechada está a boca, mais forte é o sopro.\nInvertido: quanto mais aberta está a boca, mais forte é o sopro.", 
                     font=("Segoe UI", 10), text_color="#666666", wraplength=400).pack(pady=(0, 10))

        # Mouth Peak
        ctk.CTkLabel(frm, text="Limite superior de sopro (Mouth Max). Define o ponto extremo onde o volume é máximo. Valores baixos exigem bico mais fechado quando a lógica de sopro é padrão.", 
                     font=("Segoe UI", 11), text_color="#aaaaaa", wraplength=400, justify="center").pack(fill="x")
        # Display convertido para 0-100 (x1000 sobre o float)
        val_peak = int(self.custom_mouth_peak * 1000)
        self.lbl_mouth_peak = self._create_selector(frm, val_peak, "", 1, self.update_mouth_peak)

        # Mouth Max
        ctk.CTkLabel(frm, text="Limite inferior de sopro (Mouth Min). Define o ponto extremo onde o volume é minimo.", 
                     font=("Segoe UI", 11), text_color="#aaaaaa", wraplength=400, justify="center").pack(fill="x", pady=(10, 0))
        val_max = int(self.custom_mouth_max * 1000)
        self.lbl_mouth_max = self._create_selector(frm, val_max, "", 1, self.update_mouth_max)

        # Seção Furos
        ctk.CTkFrame(self.advanced_frame, height=2, fg_color="#333333").pack(fill="x", padx=15, pady=10)
        frm_holes = ctk.CTkFrame(self.advanced_frame, fg_color="transparent")
        frm_holes.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(frm_holes, text="PRECISÃO", font=("Segoe UI", 12, "bold"), text_color="#005bb0", anchor="center").pack(fill="x")
        ctk.CTkLabel(frm_holes, text="Tamanho e espaçamento dos furos na tela.", font=("Segoe UI", 11), text_color="#aaaaaa").pack(pady=(0, 10))

        self.seg_hole_size = ctk.CTkSegmentedButton(
            frm_holes, values=["Pequeno", "Médio", "Grande"],
            command=self.update_hole_size,
            selected_color="#005bb0", unselected_color="#333333"
        )
        self.seg_hole_size.set(self.custom_hole_size)
        self.seg_hole_size.pack(pady=5)

        self._build_recording_section()

    def _build_keyboard_options(self):
        frm_audio = ctk.CTkFrame(self.advanced_frame, fg_color="transparent")
        frm_audio.pack(fill="x", padx=10, pady=5)
        
        ctk.CTkLabel(frm_audio, 
                     text="ÁUDIO", 
                     font=("Segoe UI", 12, "bold"), 
                     text_color="#005bb0", 
                     anchor="center").pack(fill="x")
        ctk.CTkLabel(frm_audio, 
                     text="Tempo de sustentação da nota após soltar a tecla (Sustain Decay). O tempo minimo e máximo varia de acordo com o Preset escolhido, portanto valores extremos podem as vezes não ter efeito.", 
                     font=("Segoe UI", 11), 
                     text_color="#aaaaaa", 
                     wraplength=500,
                     anchor="center").pack(fill="x")
        self.lbl_sustain_val = self._create_selector(frm_audio, self.custom_sustain, "s", 0.1, self.update_sustain)

        ctk.CTkFrame(self.advanced_frame, height=2, fg_color="#333333").pack(fill="x", padx=15, pady=5)

        frm_input = ctk.CTkFrame(self.advanced_frame, fg_color="transparent")
        frm_input.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(frm_input, text="PRECISÃO", font=("Segoe UI", 12, "bold"), text_color="#005bb0", anchor="center").pack(fill="x")
        
        ctk.CTkLabel(frm_input,  text="Sensibilidade da Mesa (Touch Tolerance). Quanto maior o valor, mais sensível fica a linha do teclado ao considerar um toque.", 
                     font=("Segoe UI", 11), 
                     text_color="#aaaaaa", 
                     wraplength=500,
                     anchor="center").pack(fill="x", pady=(5,0))
        self.lbl_lift_val = self._create_selector(frm_input, int(self.custom_lift * 1000), "", 5, self.update_lift)

        ctk.CTkLabel(frm_input,text="Altura miníma para armar o toque (Lift Threshold). Quanto maior o valor, mais alto você precisa levantar o dedo para teclar.", 
                     font=("Segoe UI", 11), 
                     text_color="#aaaaaa",
                     wraplength=500, 
                     anchor="center").pack(fill="x", pady=(5,0))
        self.lbl_tolerance_val = self._create_selector(frm_input, int(self.custom_tolerance * 1000), "", 1, self.update_tolerance)

        self._build_recording_section()

    def _build_drums_options(self):
        frm_drum = ctk.CTkFrame(self.advanced_frame, fg_color="transparent")
        frm_drum.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(frm_drum, text="PRECISÃO",  font=("Segoe UI", 12, "bold"), text_color="#005bb0", anchor="center").pack(fill="x")
        
        ctk.CTkLabel(frm_drum, 
                      text="Tamanho da Área de Toque (Touch Tolerance). Quanto maior a porcentagem, maior será a área de contato com os tambores, pratos, bumbo.", 
                     font=("Segoe UI", 11), text_color="#aaaaaa", anchor="center", justify="center", wraplength=400).pack(fill="x", pady=(5,10))
        
        pct = int((1.0 - self.custom_tolerance) * 100)
        self.lbl_drum_pct = self._create_selector(frm_drum, pct, "%", 1, self.update_drum_tolerance)

        # --- TOUCH VELOCITY ---
        ctk.CTkLabel(frm_drum, text="Velocidade mínima para bater o tambor (Touch Velocity). Quanto maior, mais rápido você precisa mover a mão para gerar o som.", 
                     font=("Segoe UI", 11), text_color="#aaaaaa", wraplength=400, justify="center").pack(pady=(10, 0)) 
        self.lbl_touch_velocity = self._create_selector(frm_drum, int(self.custom_touch_velocity*1000), "", 1, self.update_touch_velocity)

        self._build_recording_section()

    def _build_recording_section(self):
        ctk.CTkFrame(self.advanced_frame, height=2, fg_color="#333333").pack(fill="x", padx=15, pady=5)


        frm_rec_adv = ctk.CTkFrame(self.advanced_frame, fg_color="transparent") 
        frm_rec_adv.pack(fill="x", padx=10, pady=10) 
        ctk.CTkLabel(frm_rec_adv, text="GRAVAÇÃO", font=("Segoe UI", 12, "bold"), text_color="#005bb0", anchor="center").pack(fill="x")
        frm_checks = ctk.CTkFrame(frm_rec_adv, fg_color="transparent")
        frm_checks.pack(pady=5)
        
        self.chk_mid_adv = ctk.CTkCheckBox(frm_checks, text=".MID", variable=self.var_mid, font=("Segoe UI", 12), 
                                            width=60, fg_color="#005bb0", hover_color="#003E90") 
        self.chk_mid_adv.pack(side="left", padx=10) 
        
        self.chk_mp3_adv = ctk.CTkCheckBox(frm_checks, text=".MP3", variable=self.var_mp3, 
                                            font=("Segoe UI", 12), width=60, fg_color="#005bb0", hover_color="#003E90") 
        self.chk_mp3_adv.pack(side="left", padx=10) 
        
        self.chk_wav_adv = ctk.CTkCheckBox(frm_checks, text=".WAV", variable=self.var_wav, font=("Segoe UI", 12), 
                                            width=60, fg_color="#005bb0", hover_color="#003E90") 
        self.chk_wav_adv.pack(side="left", padx=10) 
        
        self.chk_folder_adv = ctk.CTkSwitch(frm_rec_adv, text="Separar pastas para playback e gravação", 
                                             variable=self.var_separate_pb, font=("Segoe UI", 11), progress_color="#005bb0") 
        self.chk_folder_adv.pack(pady=5)
        
        # [NOVO] Botão para abrir pasta
        btn_open_folder = ctk.CTkButton(frm_rec_adv, text="Abrir gravações", 
                                        font=("Segoe UI", 11), fg_color="#333333", hover_color="#444444", 
                                        height=24, command=self.open_recordings_folder)
        btn_open_folder.pack(pady=(5, 0))

    def _create_selector(self, parent, initial_val_display, unit_suffix, step, command_func):
        container = ctk.CTkFrame(parent, fg_color="transparent")
        container.pack(pady=5)
        btn_minus = ctk.CTkButton(container, text="-", width=30, height=30, font=("Arial", 16, "bold"), fg_color="#3a3a3a", hover_color="#505050", command=lambda: command_func(-step))
        btn_minus.pack(side="left", padx=5)
        lbl_display = ctk.CTkLabel(container, text=f"{initial_val_display}{unit_suffix}", font=("Consolas", 18, "bold"), width=80, fg_color="#252525", corner_radius=5)
        lbl_display.pack(side="left", padx=5)
        btn_plus = ctk.CTkButton(container, text="+", width=30, height=30, font=("Arial", 16, "bold"), fg_color="#3a3a3a", hover_color="#505050", command=lambda: command_func(step))
        btn_plus.pack(side="left", padx=5)
        return lbl_display

    def restore_defaults(self):
        self._load_defaults_from_settings()
        self._rebuild_advanced_panel() 
        print("Configurações restauradas.")

    def open_recordings_folder(self):
        # Garante que a pasta existe antes de abrir
        if not os.path.exists(self.recordings_folder):
            os.makedirs(self.recordings_folder)
        try:
            os.startfile(self.recordings_folder)
        except Exception as e:
            print(f"Erro ao abrir pasta: {e}")

    # --- Updates Flauta ---
    def update_mouth_peak(self, amount):
        # Valor base: 0.01 -> Display 10
        current_display = int(self.custom_mouth_peak * 1000)
        new_display = max(1, min(current_display + int(amount), 50)) # Max 50 (0.05)
        self.custom_mouth_peak = new_display / 1000.0
        self.lbl_mouth_peak.configure(text=f"{new_display}")

    def update_mouth_max(self, amount):
        current_display = int(self.custom_mouth_max * 1000)
        new_display = max(20, min(current_display + int(amount), 200)) # Max 200 (0.2)
        self.custom_mouth_max = new_display / 1000.0
        self.lbl_mouth_max.configure(text=f"{new_display}")

    def update_hole_size(self, value):
        self.custom_hole_size = value

    # --- Updates Teclado/Bateria ---
    def update_sustain(self, amount):
        new_val = round(max(0.1, self.custom_sustain + amount), 1)
        self.custom_sustain = new_val
        self.lbl_sustain_val.configure(text=f"{new_val:.1f}s")

    def update_touch_velocity(self, amount):
        new_val = max(1, min(int(self.custom_touch_velocity*1000)+amount, 100))
        self.custom_touch_velocity = new_val/1000.0
        self.lbl_touch_velocity.configure(text=f"{new_val}")

    def update_lift(self, amount):
        current_int = int(self.custom_lift * 1000)
        new_int = max(5, min(current_int + int(amount), 100))
        self.custom_lift = new_int / 1000.0
        self.lbl_lift_val.configure(text=f"{new_int}")

    def update_tolerance(self, amount):
        current_int = int(self.custom_tolerance * 1000)
        new_int = max(1, min(current_int + int(amount), 100))
        self.custom_tolerance = new_int / 1000.0
        self.lbl_tolerance_val.configure(text=f"{new_int}")

    def update_drum_tolerance(self, amount):
        current_pct = int((1.0 - self.custom_tolerance) * 100)
        new_pct = max(50, min(current_pct + int(amount), 100))
        self.custom_tolerance = round(1.0 - (new_pct / 100.0), 3)
        self.lbl_drum_pct.configure(text=f"{new_pct}%")

    def confirm_selection(self):
        self.selected_instrument = self.instruments[self.current_index]
        self.selected_type = self.current_type
        self.destroy()

def show_menu_and_start():
    if not settings.INSTRUMENTS:
        print("Erro: Nenhum instrumento encontrado.")
        return

    while True:
        app = InstrumentSelector()
        app.mainloop()
        
        chosen = app.selected_instrument
        instr_type = app.selected_type
        
        if chosen is None:
            print("Aplicação encerrada.")
            sys.exit()

        rec_opts = {
            "save_mid": app.var_mid.get(),
            "save_mp3": app.var_mp3.get(),
            "save_wav": app.var_wav.get(),
            "separate_playback": app.var_separate_pb.get()
        }

        print(f"\n>>> INICIANDO {instr_type.upper()}: {chosen}")
        
        try:
            if instr_type == "Bateria":
                drums = import_module("instruments.drums")
                drums.start_drums(
                    chosen_instrument=chosen,
                    user_tolerance=app.custom_tolerance,
                    rec_options=rec_opts,
                    touch_velocity=app.custom_touch_velocity,
                )
            elif instr_type == "Flauta":
                flute = import_module("instruments.flute")
                reload(flute)
                
                h_radius = 0.019
                h_spacing = 0.068
                if app.custom_hole_size == "Pequeno":
                    h_radius, h_spacing = 0.015, 0.058
                elif app.custom_hole_size == "Grande":
                    h_radius, h_spacing = 0.023, 0.077
                
                flute.start_flute(
                    chosen_instrument=chosen,
                    mouth_peak=app.custom_mouth_peak,
                    mouth_max=app.custom_mouth_max,
                    hole_radius=h_radius,
                    hole_spacing=h_spacing,
                    invert_blow=app.var_invert_blow.get(),
                    rec_options=rec_opts
                )
            else:
                keyboard = import_module("instruments.keyboard")
                keyboard.start_piano(
                    chosen_instrument=chosen, 
                    user_sustain=app.custom_sustain,
                    lift_threshold=app.custom_lift,
                    touch_tolerance=app.custom_tolerance,
                    rec_options=rec_opts
                )
            print(">>> Retornando ao Menu...")
            
        except Exception as e:
            print(f"Erro Crítico: {e}")
            import traceback
            traceback.print_exc()
            break

if __name__ == "__main__":
    show_menu_and_start()