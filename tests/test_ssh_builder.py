from ssh_jumpboard.config import Config
from ssh_jumpboard import ssh_builder


def test_build_jump_command():
    cfg = Config(jump_user="alice", jump_ip="1.2.3.4")
    assert ssh_builder.build_jump_command(cfg) == ["ssh", "-A", "alice@1.2.3.4"]


def test_preview_chain():
    cfg = Config(jump_user="bob", jump_ip="jump.example")
    preview = ssh_builder.preview_chain(cfg, "target.example")
    assert preview == "\n".join(["ssh -A bob@jump.example", "ssh target.example"])
