import customtkinter as ctk
from importlib import import_module
import sys
import config.settings as settings  

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("green")

class InstrumentSelector(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # --- ORGANIZAÇÃO DO CATÁLOGO ---
        self.catalog = {"Teclado": [], "Bateria": []}
        
        # Separa os instrumentos com base na configuração do settings.py
        for name, data in settings.INSTRUMENTS.items():
            sf_key = data[0] 
            if sf_key == "drums":
                self.catalog["Bateria"].append(name)
            else:
                self.catalog["Teclado"].append(name)
        
        self.current_type = "Teclado"
        if not self.catalog["Teclado"] and self.catalog["Bateria"]:
            self.current_type = "Bateria"
            
        self.instruments = self.catalog[self.current_type]
        self.current_index = 0
        self.selected_instrument = None
        self.selected_type = None
        
        self._load_defaults_from_settings()

        def_mid = getattr(settings, 'RECORD_SAVE_MID', True)
        def_mp3 = getattr(settings, 'RECORD_SAVE_MP3', False)
        def_wav = getattr(settings, 'RECORD_SAVE_WAV', False)
        def_pb_folder = getattr(settings, 'RECORD_SEPARATE_PLAYBACK_FOLDER', False)

        # Inicializa as variáveis da GUI com os valores do settings
        self.var_mid = ctk.BooleanVar(value=def_mid)
        self.var_mp3 = ctk.BooleanVar(value=def_mp3)
        self.var_wav = ctk.BooleanVar(value=def_wav)
        self.var_separate_pb = ctk.BooleanVar(value=def_pb_folder)

        self.is_advanced_open = False

        self.base_height = 250
        self.expanded_height = 550

        
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

        self.seg_type = ctk.CTkSegmentedButton(
            self.main_frame,
            values=["Teclado", "Bateria"],
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
            fg_color="#00b050", hover_color="#009040", text_color="white",
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
        self.custom_sustain = float(getattr(settings, 'SUSTAIN_DECAY', 0.8))
        self.custom_lift = float(getattr(settings, 'LIFT_THRESHOLD', 0.02))
        self.custom_tolerance = float(getattr(settings, 'TOUCH_TOLERANCE', 0.005))
        self.custom_touch_velocity = float(getattr(settings, 'TOUCH_VELOCITY', 0.012))
        

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
        else:
            self._build_drums_options()
            
        ctk.CTkFrame(self.advanced_frame, height=1, fg_color="#333333").pack(fill="x", padx=40, pady=(15, 5))
        self.btn_reset = ctk.CTkButton(
            self.advanced_frame, text="Restaurar", font=("Segoe UI", 11),
            fg_color="transparent", border_width=1, border_color="#555555", 
            hover_color="#333333", text_color="#888888", 
            height=24, width=120,
            command=self.restore_defaults
        )
        self.btn_reset.pack(pady=(5, 15))

    def _build_keyboard_options(self):
        frm_audio = ctk.CTkFrame(self.advanced_frame, fg_color="transparent")
        frm_audio.pack(fill="x", padx=10, pady=5)
        
        ctk.CTkLabel(frm_audio, 
                     text="ÁUDIO", 
                     font=("Segoe UI", 12, "bold"), 
                     text_color="#00b050", 
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

        ctk.CTkLabel(frm_input, text="PRECISÃO", font=("Segoe UI", 12, "bold"), text_color="#00b050", anchor="center").pack(fill="x")
        
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

        ctk.CTkFrame(self.advanced_frame, height=2, fg_color="#333333").pack(fill="x", padx=15, pady=5)

        frm_rec_adv = ctk.CTkFrame(self.advanced_frame, fg_color="transparent") 
        frm_rec_adv.pack(fill="x", padx=10, pady=10) 
        ctk.CTkLabel(frm_rec_adv, text="GRAVAÇÃO", font=("Segoe UI", 12, "bold"), text_color="#00b050", anchor="center").pack(fill="x")
        self.chk_mid_adv = ctk.CTkCheckBox(frm_rec_adv, text=".MID", variable=self.var_mid, font=("Segoe UI", 12), 
                                        width=60, fg_color="#00b050", hover_color="#009040") 
        self.chk_mid_adv.pack(side="left", padx=10) 
        self.chk_mp3_adv = ctk.CTkCheckBox(frm_rec_adv, text=".MP3", variable=self.var_mp3, 
                                           font=("Segoe UI", 12), width=60, fg_color="#00b050", hover_color="#009040") 
        self.chk_mp3_adv.pack(side="left", padx=10) 
        self.chk_wav_adv = ctk.CTkCheckBox(frm_rec_adv, text=".WAV", variable=self.var_wav, font=("Segoe UI", 12), 
                                           width=60, fg_color="#00b050", hover_color="#009040") 
        self.chk_wav_adv.pack(side="left", padx=10) 
        self.chk_folder_adv = ctk.CTkSwitch(frm_rec_adv, text="Separar pastas para playback e gravação", 
                                            variable=self.var_separate_pb, font=("Segoe UI", 11), progress_color="#00b050") 
        self.chk_folder_adv.pack(pady=5)

    def _build_drums_options(self):
        frm_drum = ctk.CTkFrame(self.advanced_frame, fg_color="transparent")
        frm_drum.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(frm_drum, text="PRECISÃO",  font=("Segoe UI", 12, "bold"), text_color="#00b050", anchor="center").pack(fill="x")
        
        ctk.CTkLabel(frm_drum, 
                      text="Tamanho da Área de Toque (Touch Tolerance). Quanto maior a porcentagem, maior será a área de contato com os tambores, pratos, bumbo.", 
                     font=("Segoe UI", 11), text_color="#aaaaaa", anchor="center", justify="center", wraplength=400).pack(fill="x", pady=(5,10))
        
        pct = int((1.0 - self.custom_tolerance) * 100)
        self.lbl_drum_pct = self._create_selector(frm_drum, pct, "%", 1, self.update_drum_tolerance)

        # --- TOUCH VELOCITY ---
        drum_touch_velocity = float(getattr(settings, 'TOUCH_VELOCITY', 0.012)) 
        self.custom_touch_velocity = drum_touch_velocity 
        ctk.CTkLabel(frm_drum, text="Velocidade mínima para bater o tambor (Touch Velocity). Quanto maior, mais rápido você precisa mover a mão para gerar o som.", 
                     font=("Segoe UI", 11), text_color="#aaaaaa", wraplength=400, justify="center").pack(pady=(10, 0)) 
        self.lbl_touch_velocity = self._create_selector(frm_drum, int(self.custom_touch_velocity*1000), "", 1, self.update_touch_velocity)

        ctk.CTkFrame(self.advanced_frame, height=2, fg_color="#333333").pack(fill="x", padx=15, pady=5)
        
        frm_rec_adv = ctk.CTkFrame(self.advanced_frame, fg_color="transparent") 
        frm_rec_adv.pack(fill="x", padx=10, pady=10) 
        ctk.CTkLabel(frm_rec_adv, text="GRAVAÇÃO", font=("Segoe UI", 12, "bold"), text_color="#00b050", anchor="center").pack(fill="x")
        self.chk_mid_adv = ctk.CTkCheckBox(frm_rec_adv, text=".MID", variable=self.var_mid, font=("Segoe UI", 12), 
                                        width=60, fg_color="#00b050", hover_color="#009040") 
        self.chk_mid_adv.pack(side="left", padx=10) 
        self.chk_mp3_adv = ctk.CTkCheckBox(frm_rec_adv, text=".MP3", variable=self.var_mp3, 
                                           font=("Segoe UI", 12), width=60, fg_color="#00b050", hover_color="#009040") 
        self.chk_mp3_adv.pack(side="left", padx=10) 
        self.chk_wav_adv = ctk.CTkCheckBox(frm_rec_adv, text=".WAV", variable=self.var_wav, font=("Segoe UI", 12), 
                                           width=60, fg_color="#00b050", hover_color="#009040") 
        self.chk_wav_adv.pack(side="left", padx=10) 
        self.chk_folder_adv = ctk.CTkSwitch(frm_rec_adv, text="Separar pastas para playback e gravação", 
                                            variable=self.var_separate_pb, font=("Segoe UI", 11), progress_color="#00b050") 
        self.chk_folder_adv.pack(pady=5)

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