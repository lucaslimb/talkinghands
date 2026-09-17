"""Controlador da iluminação endereçável via Arduino/USB.

Protocolo enviado ao Arduino, uma linha por comando::

    COLOR <vermelho> <verde> <azul>\n
    OFF\n
O firmware do Arduino deve interpretar essas linhas e atualizar o LED.
"""

from __future__ import annotations

import time
from typing import Optional, Tuple

try:
    import serial
    from serial import SerialException
    from serial.tools import list_ports
except ImportError:  # Permite importar o projeto antes de instalar a dependência.
    serial = None
    list_ports = None

    class SerialException(Exception):
        """Exceção compatível quando pyserial não está instalado."""


RGB = Tuple[int, int, int]


class LightingController:
    """Controla um LED/fita endereçável conectado a um Arduino."""

    def __init__(
        self,
        port: Optional[str] = None,
        baudrate: int = 115200,
        timeout: float = 1.0,
        startup_delay: float = 2.0,
        auto_connect: bool = True,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.startup_delay = startup_delay
        self._serial: Optional[object] = None

        if auto_connect:
            self.connect()

    @property
    def is_connected(self) -> bool:
        return bool(self._serial and getattr(self._serial, "is_open", False))

    @staticmethod
    def detect_port() -> Optional[str]:
        """Localiza Arduino/CP210x sem depender do número da porta COM."""
        if list_ports is None:
            return None

        candidates = []
        for info in list_ports.comports():
            text = " ".join(
                str(value or "")
                for value in (info.device, info.description, info.manufacturer, info.product)
            ).lower()
            vid_pid = (getattr(info, "vid", None), getattr(info, "pid", None))
            is_known_usb = vid_pid in {
                (0x10C4, 0xEA60),  # Silicon Labs CP2102/CP2102N
                (0x2341, 0x0043),  # Arduino Uno R3
                (0x2341, 0x0001),  # Arduino Uno antigo
                (0x2A03, 0x0043),  # Arduino.cc Uno
            }
            looks_like_arduino = any(
                token in text for token in ("arduino", "cp210", "silicon labs", "usb serial")
            )
            if is_known_usb or looks_like_arduino:
                candidates.append(info.device)

        if len(candidates) == 1:
            return candidates[0]
        return None

    def connect(self) -> None:
        """Abre a porta serial do Arduino."""
        if serial is None:
            raise RuntimeError(
                "A dependência pyserial não está instalada. "
                "Instale-a com: pip install pyserial"
            )
        if self.is_connected:
            return

        if not self.port:
            self.port = self.detect_port()
        if not self.port:
            raise ConnectionError(
                "Nenhum Arduino/CP210x foi detectado. Verifique o cabo e o driver USB."
            )

        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                write_timeout=self.timeout,
            )
            # Abrir a serial normalmente reinicia o Arduino Uno via DTR/RTS.
            # Aguarda o boot antes de enviar o primeiro comando.
            if self.startup_delay > 0:
                time.sleep(self.startup_delay)
        except SerialException as exc:
            raise ConnectionError(
                f"Não foi possível abrir o Arduino em {self.port}: {exc}"
            ) from exc

    def _send(self, command: str) -> None:
        if not self.is_connected:
            raise ConnectionError("O controlador de iluminação não está conectado.")

        try:
            self._serial.write(f"{command}\n".encode("ascii"))  # type: ignore[union-attr]
            self._serial.flush()  # type: ignore[union-attr]
        except (SerialException, OSError) as exc:
            raise ConnectionError(f"Falha ao enviar comando ao Arduino: {exc}") from exc

    @staticmethod
    def _validate_rgb(red: int, green: int, blue: int) -> RGB:
        values = (red, green, blue)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise TypeError("As componentes RGB devem ser inteiros.")
        if any(value < 0 or value > 255 for value in values):
            raise ValueError("As componentes RGB devem estar entre 0 e 255.")
        return red, green, blue

    def set_color(self, red: int, green: int, blue: int) -> None:
        """Define a cor RGB do LED."""
        red, green, blue = self._validate_rgb(red, green, blue)
        self._send(f"COLOR {red} {green} {blue}")

    def off(self) -> None:
        """Apaga o LED."""
        self._send("OFF")

    def flash(self, red: int, green: int, blue: int, duration_ms: int = 220) -> None:
        """Acende a fita inteira e solicita fadeout no Arduino."""
        red, green, blue = self._validate_rgb(red, green, blue)
        if not isinstance(duration_ms, int) or duration_ms <= 0 or duration_ms > 5000:
            raise ValueError("duration_ms deve ser um inteiro entre 1 e 5000.")
        self._send(f"FLASH {red} {green} {blue} {duration_ms}")

    def drum_hit(self, cymbal: bool, duration_ms: int = 220) -> None:
        """Dispara verde para tambores ou roxo para pratos."""
        if cymbal:
            self.flash(190, 0, 255, duration_ms)
        else:
            self.flash(0, 255, 0, duration_ms)

    def keyboard_key(self, index: int, total_keys: int, pressed: bool) -> None:
        """Acende/apaga a seção da fita correspondente a uma tecla."""
        if not isinstance(index, int) or not isinstance(total_keys, int):
            raise TypeError("index e total_keys devem ser inteiros.")
        if index < 0 or total_keys <= 0 or index >= total_keys:
            raise ValueError("Índice de tecla inválido.")
        state = "ON" if pressed else "OFF"
        self._send(f"KEY {state} {index} {total_keys}")

    def keyboard_clear(self) -> None:
        """Apaga todas as seções do teclado na fita."""
        self._send("OFF")

    def keyboard_activity(self, active_keys: int, total_keys: int) -> None:
        """Atualiza a quantidade de teclas simultaneamente ativas."""
        if not isinstance(active_keys, int) or not isinstance(total_keys, int):
            raise TypeError("active_keys e total_keys devem ser inteiros.")
        if active_keys < 0 or total_keys <= 0 or active_keys > total_keys:
            raise ValueError("Quantidade de teclas inválida.")
        self._send(f"KEYCOUNT {active_keys} {total_keys}")

    def maestro_state(self, red: int, green: int, blue: int, brightness: int) -> None:
        """Atualiza a cor da emoção e o brilho do modo Maestro."""
        red, green, blue = self._validate_rgb(red, green, blue)
        if not isinstance(brightness, int) or brightness < 0 or brightness > 255:
            raise ValueError("brightness deve ser um inteiro entre 0 e 255.")
        self._send(f"MAESTRO {red} {green} {blue} {brightness}")

    def start_idle(self) -> None:
        """Inicia o padrão de espera executado pelo Arduino."""
        self._send("IDLE ON")

    def stop_idle(self) -> None:
        """Interrompe o padrão de espera e apaga o LED."""
        # OFF também é entendido pelo firmware anterior ao modo idle.
        self._send("OFF")

    def close(self) -> None:
        """Fecha a porta serial."""
        if self._serial is not None and getattr(self._serial, "is_open", False):
            self._serial.close()  # type: ignore[union-attr]
        self._serial = None

    def __enter__(self) -> "LightingController":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


class IdleLightingService:
    """Coordena o modo idle e seu atalho durante toda a aplicação."""

    def __init__(self, controller: LightingController) -> None:
        self.controller = controller
        self.enabled = False
        self._suspended_enabled = False

    def start(self) -> None:
        self.controller.start_idle()
        self.enabled = True

    def toggle(self) -> bool:
        if self.enabled:
            self.controller.stop_idle()
            self.enabled = False
        else:
            self.controller.start_idle()
            self.enabled = True
        return self.enabled

    def suspend(self) -> None:
        """Suspende temporariamente o idle durante um modo de prática/jogo."""
        self._suspended_enabled = self.enabled
        self.controller.stop_idle()
        self.enabled = False

    def resume(self) -> None:
        """Restaura o idle após o retorno ao menu, se estava ativo antes."""
        if self._suspended_enabled:
            self.controller.start_idle()
            self.enabled = True
        self._suspended_enabled = False

    def shutdown(self) -> None:
        """Apaga o LED e fecha a conexão; seguro para chamar mais de uma vez."""
        try:
            if self.controller.is_connected:
                self.controller.off()
        finally:
            self.controller.close()
