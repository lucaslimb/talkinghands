import customtkinter as ctk
from importlib import import_module
import sys
import settings  # Importa configurações

# Configuração inicial do tema
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("green")

class InstrumentSelector(ctk.CTk):
    def __init__(self, instruments_dict):
        super().__init__()
        
        # Dados
        self.instruments = list(instruments_dict.keys())
        self.current_index = 0
        self.selected_instrument = None
        
        # Carrega default do settings ou usa 0.8 como fallback
        default_sustain = getattr(settings, 'SUSTAIN_DECAY', 0.8)
        self.custom_sustain = float(default_sustain)
        self.is_advanced_open = False

        # Configuração da Janela (Altura inicial menor)
        self.base_height = 380
        self.expanded_height = 480
        
        self.title("Talking Hands Launcher")
        self.geometry(f"600x{self.base_height}")
        self.resizable(False, False)
        self._center_window(600, self.base_height)

        # Layout Grid Principal
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Frame Principal
        self.main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main_frame.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        
        self.main_frame.grid_columnconfigure(1, weight=1)
        # Rows: 0=Title, 1=Carousel, 2=AdvancedBtn, 3=AdvancedPanel
        self.main_frame.grid_rowconfigure((0, 1), weight=0)

        # --- Título ---
        self.lbl_title = ctk.CTkLabel(
            self.main_frame,
            text="Selecione o Preset do Instrumento",
            font=("Roboto Medium", 20),
            text_color="#808080"
        )
        self.lbl_title.grid(row=0, column=0, columnspan=3, sticky="s", pady=(0, 20))

        # --- Botões de Controle (Carrossel) ---
        arrow_font = ("Segoe UI", 32, "bold")
        main_font = ("Segoe UI", 24, "bold")

        # Botão Esquerda (<)
        self.btn_prev = ctk.CTkButton(
            self.main_frame, text="❮", font=arrow_font,
            width=60, height=60, corner_radius=30,
            fg_color="#2b2b2b", hover_color="#404040",
            command=lambda: self.change_preset(-1)
        )
        self.btn_prev.grid(row=1, column=0, padx=(0, 20))

        # Botão Central (Start)
        self.btn_start = ctk.CTkButton(
            self.main_frame,
            text=self.instruments[0].upper(),
            font=main_font,
            height=80, width=300, corner_radius=40,
            fg_color="#00b050", hover_color="#009040", text_color="white",
            command=self.confirm_selection
        )
        self.btn_start.grid(row=1, column=1, sticky="ew")

        # Botão Direita (>)
        self.btn_next = ctk.CTkButton(
            self.main_frame, text="❯", font=arrow_font,
            width=60, height=60, corner_radius=30,
            fg_color="#2b2b2b", hover_color="#404040",
            command=lambda: self.change_preset(1)
        )
        self.btn_next.grid(row=1, column=2, padx=(20, 0))

        # --- Botão Toggle Avançado ---
        self.btn_advanced = ctk.CTkButton(
            self.main_frame,
            text="Avançado ▼",
            font=("Consolas", 12),
            fg_color="transparent", border_width=1, border_color="#444444",
            text_color="#888888", hover_color="#333333",
            height=28, width=120,
            command=self.toggle_advanced
        )
        self.btn_advanced.grid(row=2, column=0, columnspan=3, sticky="n", pady=(40, 10))

        # --- Painel Avançado (Inicialmente Oculto) ---
        self.advanced_frame = ctk.CTkFrame(self.main_frame, fg_color="#222222", corner_radius=10)
        
        # Label Descrição Pequena
        self.lbl_desc = ctk.CTkLabel(
            self.advanced_frame,
            text="Ajuste o tempo de sustentação (decay) da nota após soltar a tecla. O tempo minimo varia de acordo com o Preset escolhido, portanto valores pequenos podem as vezes não ter efeito.",
            font=("Segoe UI", 11),
            text_color="#aaaaaa",
            wraplength=500
        )
        self.lbl_desc.pack(pady=(15, 5), padx=10)

        # Container do Seletor Numérico
        self.selector_container = ctk.CTkFrame(self.advanced_frame, fg_color="transparent")
        self.selector_container.pack(pady=(0, 15))

        # Botão Menos (-)
        self.btn_minus = ctk.CTkButton(
            self.selector_container, text="-", width=35, height=35,
            font=("Arial", 18, "bold"), fg_color="#3a3a3a", hover_color="#505050",
            command=lambda: self.update_sustain(-0.1)
        )
        self.btn_minus.pack(side="left", padx=10)

        # Display do Valor
        self.lbl_value_display = ctk.CTkLabel(
            self.selector_container,
            text=f"{self.custom_sustain:.1f}s",
            font=("Consolas", 20, "bold"),
            width=80,
            fg_color="#1a1a1a",
            corner_radius=6
        )
        self.lbl_value_display.pack(side="left", padx=5)

        # Botão Mais (+)
        self.btn_plus = ctk.CTkButton(
            self.selector_container, text="+", width=35, height=35,
            font=("Arial", 18, "bold"), fg_color="#3a3a3a", hover_color="#505050",
            command=lambda: self.update_sustain(0.1)
        )
        self.btn_plus.pack(side="left", padx=10)


        # Bindings
        self.bind("<Left>", lambda e: self.change_preset(-1))
        self.bind("<Right>", lambda e: self.change_preset(1))
        self.bind("<Return>", lambda e: self.confirm_selection())

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
            # Fechar
            self.advanced_frame.grid_forget()
            self.btn_advanced.configure(text="Avançado ▼")
            self.geometry(f"600x{self.base_height}")
            self.is_advanced_open = False
        else:
            # Abrir
            self.advanced_frame.grid(row=3, column=0, columnspan=3, sticky="ew", pady=0)
            self.btn_advanced.configure(text="Avançado ▲")
            self.geometry(f"600x{self.expanded_height}")
            self.is_advanced_open = True

    def update_sustain(self, amount):
        new_val = self.custom_sustain + amount
        # Validação para não ser menor que zero
        if new_val < 0:
            new_val = 0.0
        
        self.custom_sustain = round(new_val, 1) # Arredonda para 1 casa decimal
        self.lbl_value_display.configure(text=f"{self.custom_sustain:.1f}s")

    def confirm_selection(self):
        self.selected_instrument = self.instruments[self.current_index]
        self.destroy()

def show_menu_and_start():
    if not settings.INSTRUMENTS:
        print("Erro: Nenhum instrumento encontrado em settings.py")
        return

    # Loop Infinito para retornar ao menu
    while True:
        app = InstrumentSelector(settings.INSTRUMENTS)
        app.mainloop()
        
        # Recupera os dados APÓS a janela fechar
        chosen = app.selected_instrument
        sustain_val = app.custom_sustain 

        # Se o usuário fechou a janela (X) sem escolher, encerra o script
        if chosen is None:
            print("Menu fechado. Encerrando aplicação.")
            sys.exit()

        print(f"\n>>> Iniciando Piano: {chosen} | Sustain: {sustain_val}s <<<\n")

        try:
            keyboard = import_module("keyboard")
            keyboard.start_piano(chosen, sustain_val)
            print(">>> Retornando ao Menu Principal...")
        except Exception as e:
            print(f"Erro Crítico ao executar piano: {e}")
            break

if __name__ == "__main__":
    show_menu_and_start()