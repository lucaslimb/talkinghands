import customtkinter as ctk
from importlib import import_module
import sys
import config.settings as settings  

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("green")

class InstrumentSelector(ctk.CTk):
    def __init__(self, instruments_dict):
        super().__init__()
        
        self.instruments = list(instruments_dict.keys())
        self.current_index = 0
        self.selected_instrument = None
        
        self._load_defaults_from_settings()

        self.is_advanced_open = False

        self.base_height = 250
        self.expanded_height = 500
        
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
        self.main_frame.grid_rowconfigure((0, 1), weight=0)

        # --- Título ---
        self.lbl_title = ctk.CTkLabel(
            self.main_frame,
            text="Selecione o Preset",
            font=("Roboto Medium", 20), text_color="#808080"
        )
        self.lbl_title.grid(row=0, column=0, columnspan=3, sticky="s", pady=(0, 20))

        # --- Botões de Controle (Carrossel) ---
        arrow_font = ("Segoe UI", 32, "bold")
        main_font = ("Segoe UI", 24, "bold")

        self.btn_prev = ctk.CTkButton(
            self.main_frame, text="❮", font=arrow_font, width=60, height=60, corner_radius=30,
            fg_color="#2b2b2b", hover_color="#404040", command=lambda: self.change_preset(-1)
        )
        self.btn_prev.grid(row=1, column=0, padx=(0, 20))

        self.btn_start = ctk.CTkButton(
            self.main_frame, text=self.instruments[0].upper(), font=main_font,
            height=80, width=300, corner_radius=40,
            fg_color="#00b050", hover_color="#009040", text_color="white",
            command=self.confirm_selection
        )
        self.btn_start.grid(row=1, column=1, sticky="ew")

        self.btn_next = ctk.CTkButton(
            self.main_frame, text="❯", font=arrow_font, width=60, height=60, corner_radius=30,
            fg_color="#2b2b2b", hover_color="#404040", command=lambda: self.change_preset(1)
        )
        self.btn_next.grid(row=1, column=2, padx=(20, 0))

        # --- Botão Toggle Avançado ---
        self.btn_advanced = ctk.CTkButton(
            self.main_frame, text="Avançado ▼", font=("Consolas", 12),
            fg_color="transparent", border_width=1, border_color="#444444",
            text_color="#888888", hover_color="#333333", height=28, width=160,
            command=self.toggle_advanced
        )
        self.btn_advanced.grid(row=2, column=0, columnspan=3, sticky="n", pady=(30, 10))

        # --- Painel Avançado (Container Principal) ---
        self.advanced_frame = ctk.CTkScrollableFrame(self.main_frame, fg_color="#1a1a1a", corner_radius=10)
        
        # === SEÇÃO 1: INSTRUMENTO (AUDIO) ===
        self.frm_audio = ctk.CTkFrame(self.advanced_frame, fg_color="transparent")
        self.frm_audio.pack(fill="x", padx=15, pady=10)
        
        ctk.CTkLabel(self.frm_audio, 
                     text="MOTOR DE ÁUDIO", 
                     font=("Segoe UI", 12, "bold"), 
                     text_color="#00b050", 
                     anchor="center").pack(fill="x")
        ctk.CTkLabel(self.frm_audio, 
                     text="Tempo de sustentação da nota após soltar a tecla (Sustain Decay). O tempo minimo varia de acordo com o Preset escolhido, portanto valores pequenos podem as vezes não ter efeito.", 
                     font=("Segoe UI", 11), 
                     text_color="#aaaaaa", 
                     wraplength=500,
                     anchor="center").pack(fill="x")
        
        self.lbl_sustain_val = self._create_selector(self.frm_audio, self.custom_sustain, "s", 0.1, self.update_sustain)

        # Separador Visual
        ctk.CTkFrame(self.advanced_frame, height=2, fg_color="#333333").pack(fill="x", padx=15, pady=5)

        # === SEÇÃO 2: PROGRAMA (INPUT) ===
        self.frm_input = ctk.CTkFrame(self.advanced_frame, fg_color="transparent")
        self.frm_input.pack(fill="x", padx=15, pady=10)

        ctk.CTkLabel(self.frm_input, 
                     text="CALIBRAÇÃO DE TOQUE", 
                     font=("Segoe UI", 12, "bold"), 
                     text_color="#00b050", 
                     anchor="center").pack(fill="x")
        
        ctk.CTkLabel(self.frm_input, 
                     text="Altura miníma para armar o toque (Lift Threshold). Quanto maior o valor, mais alto você precisa levantar o dedo para teclar.", 
                     font=("Segoe UI", 11), 
                     text_color="#aaaaaa",
                     wraplength=500, 
                     anchor="center").pack(fill="x", pady=(5,0))
        self.lbl_lift_val = self._create_selector(self.frm_input, int(self.custom_lift * 1000), "", 5, self.update_lift) # Passa 5 unidades (0.005)

        ctk.CTkLabel(self.frm_input, 
                     text="Sensibilidade da Mesa (Touch Tolerance). Quanto maior o valor, mais sensível fica a linha do teclado ao considerar um toque.", 
                     font=("Segoe UI", 11), 
                     text_color="#aaaaaa", 
                     wraplength=500,
                     anchor="center").pack(fill="x", pady=(5,0))
        self.lbl_tolerance_val = self._create_selector(self.frm_input, int(self.custom_tolerance * 1000), "", 1, self.update_tolerance) # Passa 1 unidade (0.001)

        ctk.CTkFrame(self.advanced_frame, height=2, fg_color="#333333").pack(fill="x", padx=15, pady=5)

        self.btn_reset = ctk.CTkButton(
            self.advanced_frame, text="Restaurar Padrão", font=("Segoe UI", 11),
            fg_color="transparent", border_width=1, border_color="#555555", 
            hover_color="#333333", text_color="#888888", 
            height=24, width=120,
            command=self.restore_defaults
        )
        self.btn_reset.pack(pady=(10, 15))

        # Bindings
        self.bind("<Left>", lambda e: self.change_preset(-1))
        self.bind("<Right>", lambda e: self.change_preset(1))
        self.bind("<Return>", lambda e: self.confirm_selection())

    def _load_defaults_from_settings(self):
        self.custom_sustain = float(getattr(settings, 'SUSTAIN_DECAY', 0.8))
        self.custom_lift = float(getattr(settings, 'LIFT_THRESHOLD', 0.02))
        self.custom_tolerance = float(getattr(settings, 'TOUCH_TOLERANCE', 0.005))

    def _create_selector(self, parent, initial_val_display, unit_suffix, step, command_func):
        container = ctk.CTkFrame(parent, fg_color="transparent")
        container.pack(pady=5)

        btn_minus = ctk.CTkButton(container, text="-", width=30, height=30, font=("Arial", 16, "bold"), 
                                fg_color="#3a3a3a", hover_color="#505050",
                                command=lambda: command_func(-step))
        btn_minus.pack(side="left", padx=5)

        lbl_display = ctk.CTkLabel(container, text=f"{initial_val_display}{unit_suffix}", font=("Consolas", 18, "bold"), width=60, fg_color="#252525", corner_radius=5)
        lbl_display.pack(side="left", padx=5)

        btn_plus = ctk.CTkButton(container, text="+", width=30, height=30, font=("Arial", 16, "bold"), 
                               fg_color="#3a3a3a", hover_color="#505050",
                               command=lambda: command_func(step))
        btn_plus.pack(side="left", padx=5)
        
        return lbl_display

    def _center_window(self, width, height):
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = (screen_width / 2) - (width / 2)
        y = (screen_height / 2) - (height / 2)
        self.geometry(f'{width}x{height}+{int(x)}+{int(y)}')

    def change_preset(self, direction):
        self.current_index = (self.current_index + direction) % len(self.instruments)
        self.btn_start.configure(text=self.instruments[self.current_index].upper())

    def toggle_advanced(self):
        if self.is_advanced_open:
            self.advanced_frame.grid_forget()
            self.btn_advanced.configure(text="Avançado ▼")
            self.geometry(f"600x{self.base_height}")
            self.is_advanced_open = False
        else:
            self.advanced_frame.grid(row=3, column=0, columnspan=3, sticky="ew", pady=0)
            self.btn_advanced.configure(text="Avançado ▲")
            self.geometry(f"600x{self.expanded_height}")
            self.is_advanced_open = True

    def restore_defaults(self):
        self._load_defaults_from_settings()
        self.lbl_sustain_val.configure(text=f"{self.custom_sustain:.1f}s")
        self.lbl_lift_val.configure(text=f"{int(self.custom_lift * 1000)}")
        self.lbl_tolerance_val.configure(text=f"{int(self.custom_tolerance * 1000)}")
    
    def update_sustain(self, amount):
        new_val = round(max(0.1, self.custom_sustain + amount), 1)
        self.custom_sustain = new_val
        self.lbl_sustain_val.configure(text=f"{new_val:.1f}s")

    def update_lift(self, amount):
        # Min: 5 (0.005) | Max: 99 (0.99)
        current_int = int(self.custom_lift * 1000)
        new_int = current_int + int(amount)
        
        # Clamp (Trava os valores)
        new_int = max(5, min(new_int, 9999)) 
        
        self.custom_lift = new_int / 1000.0
        self.lbl_lift_val.configure(text=f"{new_int}")

    def update_tolerance(self, amount):
        # Min: 1 (0.001) | Max: 10 (0.1)
        current_int = int(self.custom_tolerance * 1000)
        new_int = current_int + int(amount)
        
        new_int = max(1, min(new_int, 100)) 
        
        self.custom_tolerance = new_int / 1000.0
        self.lbl_tolerance_val.configure(text=f"{new_int}")

    def confirm_selection(self):
        self.selected_instrument = self.instruments[self.current_index]
        self.destroy()

def show_menu_and_start():
    if not settings.INSTRUMENTS:
        print("Erro: Nenhum instrumento encontrado em settings.py")
        return

    while True:
        app = InstrumentSelector(settings.INSTRUMENTS)
        app.mainloop()
        
        chosen = app.selected_instrument
        
        sustain_val = app.custom_sustain
        lift_val = app.custom_lift
        tol_val = app.custom_tolerance

        if chosen is None:
            print("Aplicação encerrada.")
            sys.exit()

        print(f"\n>>> INICIANDO: {chosen}")
        print(f"    [Config] Sustain: {sustain_val}s | Lift: {lift_val} | Tolerance: {tol_val}")

        try:
            keyboard = import_module("instruments.keyboard")
            keyboard.start_piano(
                chosen_instrument=chosen, 
                user_sustain=sustain_val,
                lift_threshold=lift_val,
                touch_tolerance=tol_val
            )
            print(">>> Retornando ao Menu...")
        except Exception as e:
            print(f"Erro Crítico: {e}")
            import traceback
            traceback.print_exc()
            break

if __name__ == "__main__":
    show_menu_and_start()