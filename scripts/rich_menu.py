from __future__ import annotations

import sys
import termios
import threading
import time
import tty
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import click
from rich.live import Live
from rich.style import Style
from rich.text import Text

if TYPE_CHECKING:
    from rich.console import Console, ConsoleOptions, RenderResult


# Function to update the last clicked key
def get_key_press() -> str:
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


class Menu:
    def __init__(
        self,
        items,
        *,
        title=None,
        select_style=None,
        non_style=None,
        lock=None,
    ) -> None:
        self.items = items
        self.title = title
        self._key_count = 0
        self.selected_item = 0

        if select_style is None:
            self.select_style = Style(color="green", bold=True)
        else:
            self.select_style = select_style

        if non_style is None:
            self.non_style = Style(color="white")
        else:
            self.non_style = non_style

        self._lock = lock if lock else threading.RLock()
        self._thread = threading.Thread(target=self.get_user_input)
        self._threadstart = False
        self._thread.start()
        self.stopsignal = False

    def display(self) -> Iterator[Text]:
        self.selected_item = self._key_count % len(self.items)
        for i, item in enumerate(self.items):
            if i == self.selected_item:
                yield Text(f"➤  {item}", style=self.select_style)
            else:
                yield Text(f"   {item}", style=self.non_style)

    def get_user_input(self) -> None:
        while not self._threadstart:
            # Wait for the first display to be done
            time.sleep(0.1)

        while not self.stopsignal:
            with self._lock:
                key = get_key_press()
                if key == "\x1b":
                    # The Escape key was pressed (arrow keys usually start with ESC)
                    char = sys.stdin.read(2)
                    if char == "[A":  # Up arrow
                        self._key_count = self._key_count - 1
                    elif char == "[B":  # Down arrow
                        self._key_count = self._key_count + 1
                elif key == "k":
                    self._key_count = self._key_count - 1
                elif key == "j":
                    self._key_count = self._key_count + 1
                elif key == "\x03":
                    # The user has pressed Ctrl-C
                    self.stopsignal = KeyboardInterrupt
                    break
                elif key == "\r":
                    self.stopsignal = True
                    break

            time.sleep(0.1)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        if self.title:
            yield self.title

        with self._lock:
            yield from self.display()

        self._threadstart = True


def live_menu(menu_items, console, **menu_kwargs) -> Any:
    with Live(console=console, transient=True) as live:
        return menu(menu_items, live=live, **menu_kwargs)


def menu(menu_items, live, **menu_kwargs) -> Any:
    menu_keys = list(menu_items)
    menu_values = menu_items.values() if isinstance(menu_items, dict) else menu_items
    menu = Menu(menu_values, lock=live._lock, **menu_kwargs)

    while not menu.stopsignal:
        live.update(menu)
        time.sleep(0.05)

    if menu.stopsignal is KeyboardInterrupt:
        raise KeyboardInterrupt

    return menu_keys[menu.selected_item]


class ArgumentMenu(click.Argument):
    def __init__(self, *args, console=None, title=None, choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.required = False
        self.choices = choices
        self.console = console
        self.title = title or "Choose an item:"

    def consume_value(self, ctx, opts):
        val = super().consume_value(ctx, opts)
        if val[0] is None:
            value = live_menu(self.choices, self.console, title=self.title)
            return (value, val[1])
        return val


def argument_menu(*param_decls, **attrs):
    return click.argument(*param_decls, cls=ArgumentMenu, **attrs)


if __name__ == "__main__":
    from rich.console import Console

    console = Console()
    menu_items = {"Option 1": "Test 1", "Option 2": "Test 2", "Option 3": "Test 3"}
    selected = live_menu(menu_items, console, title="Select an option")
    console.print(f"You selected: {selected}")
