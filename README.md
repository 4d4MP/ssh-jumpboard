# ssh-jumpboard

A tiny two-hop SSH helper with both CLI and PySide6 GUI front-ends.

## CLI usage

```
python -m ssh_jumpboard.cli init --user <user> --jump-ip <ip>
python -m ssh_jumpboard.cli connect <target>
```

Run `python -m ssh_jumpboard.cli --help` for the full command list.

## GUI

Launch with:

```
python -m ssh_jumpboard.gui
```
