import customtkinter as ctk
from importlib import import_module
import sys
import config.settings as settings  

# Configuração inicial do tema
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("green")

class InstrumentSelector(ctk.CTk):
    def __init__(self, instruments_dict):
        super().__init__()
        
        # --- ORGANIZAÇÃO DO CATÁLOGO ---
        self.catalog = {"Keyboard": [], "Drums": []}
        
        # Separa os instrumentos com base na configuração do settings.py
        # instruments_dict[name] = (sf_key, bank, preset)
        for name, data in instruments_dict.items():
            sf_key = data[0] 
            if sf_key == "drums":
                self.catalog["Drums"].append(name)
            else:
                self.catalog["Keyboard"].append(name)
        
        # Define tipo inicial
        self.current_type = "Keyboard"
        if not self.catalog["Keyboard"] and self.catalog["Drums"]:
            self.current_type = "Drums"
            
        self.instruments = self.catalog[self.current_type]
        self.current_index = 0
        self.selected_instrument = None
        self.selected_type = None # Armazena se é Keyboard ou Drums
        
        self._load_defaults_from_settings()

        self.is_advanced_open = False

        self.base_height = 300 # Aumentado levemente para caber o seletor
        self.expanded_height = 600
        
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
        # Rows: 0=TypeSelector, 1=Title, 2=Carousel, 3=AdvancedBtn, 4=Panel
        self.main_frame.grid_rowconfigure((0, 1, 2), weight=0)

        # --- SELETOR DE TIPO (NOVO) ---
        self.seg_type = ctk.CTkSegmentedButton(
            self.main_frame,
            values=["Keyboard", "Drums"],
            command=self.change_instrument_type,
            font=("Segoe UI", 14, "bold"),
            height=30
        )
        self.seg_type.set(self.current_type)
        self.seg_type.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 15), padx=80)

        # --- Título ---
        self.lbl_title = ctk.CTkLabel(
            self.main_frame,
            text="Selecione o Preset",
            font=("Roboto Medium", 20), text_color="#808080"
        )
        self.lbl_title.grid(row=1, column=0, columnspan=3, sticky="s", pady=(0, 20))

        # --- Botões de Controle (Carrossel) ---
        arrow_font = ("Segoe UI", 32, "bold")
        main_font = ("Segoe UI", 24, "bold")

        self.btn_prev = ctk.CTkButton(
            self.main_frame, text="❮", font=arrow_font, width=60, height=60, corner_radius=30,
            fg_color="#2b2b2b", hover_color="#404040", command=lambda: self.change_preset(-1)
        )
        self.btn_prev.grid(row=2, column=0, padx=(0, 20))

        # Botão Central
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
        self.btn_advanced.grid(row=3, column=0, columnspan=3, sticky="n", pady=(30, 10))

        # --- Painel Avançado (Container Principal) ---
        self.advanced_frame = ctk.CTkScrollableFrame(self.main_frame, fg_color="#1a1a1a", corner_radius=10)
        # O conteúdo agora é gerado dinamicamente em _rebuild_advanced_panel

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

    def change_instrument_type(self, value):
        """Troca a lista de instrumentos e atualiza a UI"""
        self.current_type = value
        self.instruments = self.catalog[value]
        self.current_index = 0
        
        # Atualiza botão central
        text = self.instruments[0].upper() if self.instruments else "NENHUM"
        self.btn_start.configure(text=text)
        
        # Se o painel avançado estiver aberto, atualiza para as opções do novo tipo
        if self.is_advanced_open:
            self._rebuild_advanced_panel()

    def change_preset(self, direction):
        if not self.instruments: return
        self.current_index = (self.current_index + direction) % len(self.instruments)
        self.btn_start.configure(text=self.instruments[self.current_index].upper())

    def _clear_frame(self, frame):
        for widget in frame.winfo_children():
            widget.destroy()

    def _rebuild_advanced_panel(self):
        """Reconstrói o painel avançado baseado no tipo de instrumento"""
        self._clear_frame(self.advanced_frame)
        
        if self.current_type == "Keyboard":
            self._build_keyboard_options()
        else:
            self._build_drums_options()
            
        # Botão Restaurar (Comum a ambos)
        ctk.CTkFrame(self.advanced_frame, height=2, fg_color="#333333").pack(fill="x", padx=15, pady=5)
        self.btn_reset = ctk.CTkButton(
            self.advanced_frame, text="Restaurar Padrão", font=("Segoe UI", 11),
            fg_color="transparent", border_width=1, border_color="#555555", 
            hover_color="#333333", text_color="#888888", 
            height=24, width=120,
            command=self.restore_defaults
        )
        self.btn_reset.pack(pady=(10, 15))

    def _build_keyboard_options(self):
        # === SEÇÃO 1: INSTRUMENTO (AUDIO) ===
        frm_audio = ctk.CTkFrame(self.advanced_frame, fg_color="transparent")
        frm_audio.pack(fill="x", padx=15, pady=10)
        
        ctk.CTkLabel(frm_audio, text="MOTOR DE ÁUDIO", font=("Segoe UI", 12, "bold"), text_color="#00b050", anchor="center").pack(fill="x")
        ctk.CTkLabel(self.frm_audio, 
                     text="Tempo de sustentação da nota após soltar a tecla (Sustain Decay). O tempo minimo varia de acordo com o Preset escolhido, portanto valores pequenos podem as vezes não ter efeito.", 
                     font=("Segoe UI", 11), 
                     text_color="#aaaaaa", 
                     wraplength=500,
                     anchor="center").pack(fill="x")
        self.lbl_sustain_val = self._create_selector(frm_audio, self.custom_sustain, "s", 0.1, self.update_sustain)

        ctk.CTkFrame(self.advanced_frame, height=2, fg_color="#333333").pack(fill="x", padx=15, pady=5)

        # === SEÇÃO 2: PROGRAMA (INPUT) ===
        frm_input = ctk.CTkFrame(self.advanced_frame, fg_color="transparent")
        frm_input.pack(fill="x", padx=15, pady=10)

        ctk.CTkLabel(frm_input, text="CALIBRAÇÃO DE TOQUE", font=("Segoe UI", 12, "bold"), text_color="#00b050", anchor="center").pack(fill="x")
        
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

    def _build_drums_options(self):
        # === SEÇÃO ÚNICA DA BATERIA ===
        frm_drum = ctk.CTkFrame(self.advanced_frame, fg_color="transparent")
        frm_drum.pack(fill="x", padx=15, pady=10)
        
        ctk.CTkLabel(frm_drum, text="CALIBRAÇÃO DA BATERIA", font=("Segoe UI", 12, "bold"), text_color="#00b050", anchor="center").pack(fill="x")
        
        ctk.CTkLabel(frm_drum, 
                     text="Tamanho da Área de Toque. Quanto maior a porcentagem, maior será a área de contato com os tambores, pratos, bumbo.", 
                     font=("Segoe UI", 11), text_color="#aaaaaa", anchor="center", justify="center", wraplength=400).pack(fill="x", pady=(5,10))
        
        # Calcula % baseada na tolerância (1.0 - tol) * 100
        pct = int((1.0 - self.custom_tolerance) * 100)
        self.lbl_drum_pct = self._create_selector(frm_drum, pct, "%", 1, self.update_drum_tolerance)

    def toggle_advanced(self):
        if self.is_advanced_open:
            self.advanced_frame.grid_forget()
            self.btn_advanced.configure(text="Avançado ▼")
            self.geometry(f"600x{self.base_height}")
            self.is_advanced_open = False
        else:
            self._rebuild_advanced_panel()
            self.advanced_frame.grid(row=4, column=0, columnspan=3, sticky="ew", pady=0)
            self.btn_advanced.configure(text="Avançado ▲")
            self.geometry(f"600x{self.expanded_height}")
            self.is_advanced_open = True

    def restore_defaults(self):
        self._load_defaults_from_settings()
        self._rebuild_advanced_panel() # Atualiza visualmente
    
    # --- UPDATERS KEYBOARD ---
    def update_sustain(self, amount):
        new_val = round(max(0.1, self.custom_sustain + amount), 1)
        self.custom_sustain = new_val
        self.lbl_sustain_val.configure(text=f"{new_val:.1f}s")

    def update_lift(self, amount):
        current_int = int(self.custom_lift * 1000)
        new_int = max(5, min(current_int + int(amount), 9999)) 
        self.custom_lift = new_int / 1000.0
        self.lbl_lift_val.configure(text=f"{new_int}")

    def update_tolerance(self, amount):
        current_int = int(self.custom_tolerance * 1000)
        new_int = max(1, min(current_int + int(amount), 100)) 
        self.custom_tolerance = new_int / 1000.0
        self.lbl_tolerance_val.configure(text=f"{new_int}")

    # --- UPDATER DRUMS ---
    def update_drum_tolerance(self, amount):
        # amount é +1 ou -1 (que representa mudança na %)
        # Aumentar % = Diminuir Tolerance (Mais fácil)
        
        current_pct = int((1.0 - self.custom_tolerance) * 100)
        new_pct = max(50, min(current_pct + int(amount), 100))
        
        # Converte % de volta para tolerance
        self.custom_tolerance = round(1.0 - (new_pct / 100.0), 3)
        
        self.lbl_drum_pct.configure(text=f"{new_pct}%")

    def confirm_selection(self):
        self.selected_instrument = self.instruments[self.current_index]
        self.selected_type = self.current_type # Salva o tipo (Keyboard/Drums)
        self.destroy()

def show_menu_and_start():
    if not settings.INSTRUMENTS:
        print("Erro: Nenhum instrumento encontrado em settings.py")
        return

    while True:
        app = InstrumentSelector(settings.INSTRUMENTS)
        app.mainloop()
        
        chosen = app.selected_instrument
        instr_type = app.selected_type # Recupera o tipo
        
        # Configs
        sustain_val = app.custom_sustain
        lift_val = app.custom_lift
        tol_val = app.custom_tolerance

        if chosen is None:
            print("Aplicação encerrada.")
            sys.exit()

        print(f"\n>>> INICIANDO {instr_type.upper()}: {chosen}")
        
        try:
            if instr_type == "Drums":
                drums = import_module("instruments.drums")
                # Bateria usa apenas o tolerance (convertido de %)
                drums.start_drums(
                    chosen_instrument=chosen,
                    user_tolerance=tol_val 
                )
            else:
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