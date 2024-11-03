#!/usr/bin/env python

import os.path
import runpy
import sys

GREEN, RED, RESET = "\033[0;32m", "\033[0;31m", "\033[0m"
PATH = os.path.dirname(__file__)


def custom_excepthook(exctype, value, traceback):
    if exctype is KeyboardInterrupt:
        print(f"\n{RED}Aborted.{RESET}")
        sys.exit(1)
    else:
        sys.__excepthook__(exctype, value, traceback)


sys.path.insert(0, PATH)
sys.argv.pop(0)
sys.excepthook = custom_excepthook

runpy.run_path(os.path.join(PATH, sys.argv[0]), run_name="__main__")
