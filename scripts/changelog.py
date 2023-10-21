from __future__ import annotations

import re
from textwrap import dedent

from pandas.io.clipboard import clipboard_get, clipboard_set

# https://github.com/holoviz/holoviews/releases/new


def main() -> None:
    cl = clipboard_get()

    commits = re.findall("\\* (.+?)\\.? by (@.+?) in (.+?)\n", cl)
    users, msgs = set(), ""
    for c in commits:
        no = c[2].split("/")[-1]
        msg = c[0].strip()
        msg = msg[0].upper() + msg[1:]
        msgs += f"- {msg} ([#{no}]({c[2]}))\n"
        users |= {c[1]}

    new_users = set(re.findall("\\* (@.+?) ", cl))
    users = users - new_users

    template = f"""
    New users: {", ".join(sorted(new_users, key=lambda x: x.lower()))}
    Returning users: {", ".join(sorted(users, key=lambda x: x.lower()))}

    New features:
    Enhancements:
    Bug fixes:
    Compatibility:
    Documentation:
    Maintenance:

    (Not sorted commits)
    """

    output = dedent(template) + msgs

    clipboard_set(output)
    print(output)


if __name__ == "__main__":
    main()
