from __future__ import annotations

import sys
import termios
import threading
import time
import tty
from typing import TYPE_CHECKING

from rich.live import Live

if TYPE_CHECKING:
    from rich.console import Console, ConsoleOptions, RenderResult


# Function to update the last clicked key
def get_key_press():
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(sys.stdin.fileno())
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSAFLUSH, old_settings)
    return ch


class Menu:
    def __init__(self, items):
        self.items = items
        self.selected_item = 0

        self._threadlock = threading.Lock()
        self._thread = threading.Thread(target=self.get_user_input)
        self._threadstart = False
        self._stop = False

    def display(self):
        for i, item in enumerate(self.items):
            if i == self.selected_item:
                yield f"[bold][green]➤  {item}[/green][/bold]"
            else:
                yield f"[white]   {item}[/white]"

    def get_user_input(self):
        while not self._stop:
            with self._threadlock:
                key = get_key_press()

                # Process user input
                if key == "A":
                    self.selected_item = (self.selected_item - 1) % len(self.items)
                elif key == "B":
                    self.selected_item = (self.selected_item + 1) % len(self.items)
                elif key == "\r" or key == "\n":
                    self._stop = True
                    break

            time.sleep(0.1)

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        with self._threadlock:
            for d in self.display():
                console.file.write("\r")
                yield from console.render(console.render_str(d))

        if not self._threadstart:
            self._thread.start()
            self._threadstart = True


def live_menu(menu_items, console):
    menu = Menu(menu_items.values())
    with Live(console=console) as live:
        while not menu._stop:
            time.sleep(0.01)
            live.update(menu)
    return list(menu_items)[menu.selected_item]


if __name__ == "__main__":
    from rich.console import Console

    console = Console()
    console.print("This is a test")
    menu_items = {"Option 1": "Test 1", "Option 2": "Test 2", "Option 3": "Test 3"}
    selected = live_menu(menu_items, console)
    console.print(f"You selected: {selected}")
