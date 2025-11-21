import cv2
import numpy as np

class InstrumentMenu:
    def __init__(self, instruments_dict):
        self.instruments = list(instruments_dict.keys())
        self.selected_index = -1
        self.hover_index = -1
        self.confirmed = False
        
        # Configurações visuais
        self.width, self.height = 640, 480
        self.cols = 2
        self.rows = (len(self.instruments) + 1) // self.cols
        self.btn_h = 60
        self.margin = 20
        self.start_y = 100

    def mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_MOUSEMOVE:
            self.check_hover(x, y)
        elif event == cv2.EVENT_LBUTTONDOWN:
            self.check_click(x, y)

    def check_hover(self, x, y):
        self.hover_index = self.get_index_at(x, y)

    def check_click(self, x, y):
        idx = self.get_index_at(x, y)
        if idx != -1:
            self.selected_index = idx
            self.confirmed = True

    def get_index_at(self, x, y):
        # Lógica matemática para descobrir em qual botão o mouse está
        if y < self.start_y: return -1
        
        rel_y = y - self.start_y
        row = rel_y // (self.btn_h + 10)
        
        col_width = (self.width - (2 * self.margin)) // self.cols
        if x < self.margin or x > (self.width - self.margin): return -1
        col = (x - self.margin) // col_width
        
        idx = row * self.cols + col
        
        if 0 <= idx < len(self.instruments):
            return int(idx)
        return -1

    def draw(self):
        # Fundo escuro "Cyberpunk"
        img = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        img[:] = (30, 30, 30) 

        # Título
        cv2.putText(img, "SELECIONE O SOM", (self.width//2 - 130, 50), 
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)

        col_width = (self.width - (2 * self.margin)) // self.cols

        for i, name in enumerate(self.instruments):
            row = i // self.cols
            col = i % self.cols
            
            x1 = self.margin + (col * col_width) + 5
            y1 = self.start_y + (row * (self.btn_h + 10))
            x2 = x1 + col_width - 10
            y2 = y1 + self.btn_h

            # Cores dinâmicas (Hover / Normal)
            color = (60, 60, 60) # Cinza padrão
            text_color = (200, 200, 200)

            if i == self.hover_index:
                color = (100, 100, 100) # Cinza claro (Hover)
                text_color = (255, 255, 255)
            
            cv2.rectangle(img, (x1, y1), (x2, y2), color, -1)
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 1) # Borda verde

            # Centralizar texto
            text_size = cv2.getTextSize(name, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)[0]
            text_x = x1 + (col_width - 10 - text_size[0]) // 2
            text_y = y1 + (self.btn_h + text_size[1]) // 2

            cv2.putText(img, name, (text_x, text_y), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)

        return img

def show_menu(instruments_dict):
    menu = InstrumentMenu(instruments_dict)
    window_name = "Menu de Selecao"
    cv2.namedWindow(window_name)
    cv2.setMouseCallback(window_name, menu.mouse_callback)

    selected_name = None

    while True:
        frame = menu.draw()
        cv2.imshow(window_name, frame)

        key = cv2.waitKey(1)
        if key == 27: # ESC sai
            break
        
        if menu.confirmed:
            selected_name = menu.instruments[menu.selected_index]
            # Pequeno feedback visual antes de fechar
            cv2.waitKey(200) 
            break
            
    cv2.destroyWindow(window_name)
    
    # Se fechar sem escolher, retorna o primeiro da lista
    if selected_name is None:
        return list(instruments_dict.keys())[0]
        
    return selected_name