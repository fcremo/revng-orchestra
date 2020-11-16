import os
import pty
import select
import sys
import termios
import tty
from subprocess import Popen

from loguru import logger

from ..actions.util import run_script
from ..model.configuration import Configuration
from ..util import export_environment


def install_subcommand(sub_argparser):
    cmd_parser = sub_argparser.add_parser("shell", handler=handle_shell,
                                          help="Open a shell with the given component environment (experimental)")
    cmd_parser.add_argument("component", nargs="?")


def handle_shell(args):
    config = Configuration(args)
    if not args.component:
        env = config.global_env()
        env["PS1"] = "(orchestra) $PS1"
        cd_to = os.getcwd()
    else:
        build = config.get_build(args.component)

        if not build:
            suggested_component_name = config.get_suggested_component_name(args.component)
            logger.error(f"Component {args.component} not found! Did you mean {suggested_component_name}?")
            exit(1)

        env = build.install.environment
        env["PS1"] = f"(orchestra - {build.qualified_name}) $PS1"
        if os.path.exists(build.install.environment["BUILD_DIR"]):
            cd_to = build.install.environment["BUILD_DIR"]
        else:
            cd_to = os.getcwd()

    user_shell = run_script("getent passwd $(whoami) | cut -d: -f7", quiet=True).stdout.decode("utf-8").strip()

    env_setter_script = export_environment(env)

    # From https://stackoverflow.com/a/43012138

    # save original tty setting then set it to raw mode
    old_tty = termios.tcgetattr(sys.stdin)
    tty.setraw(sys.stdin.fileno())

    # open pseudo-terminal to interact with subprocess
    master_fd, slave_fd = pty.openpty()

    # use os.setsid() make it run in a new process group, or bash job control will not be enabled
    p = Popen(user_shell,
              preexec_fn=os.setsid,
              stdin=slave_fd,
              stdout=slave_fd,
              stderr=slave_fd,
              universal_newlines=True,
              cwd=cd_to
              )

    os.write(master_fd, env_setter_script.encode("utf-8"))
    os.write(master_fd, b"echo 'RE''ADY';\n")

    prelude_passed = False
    buf = b""

    while p.poll() is None:
        r, w, e = select.select([sys.stdin, master_fd], [], [], 0.1)
        if sys.stdin in r:
            d = os.read(sys.stdin.fileno(), 10240)
            os.write(master_fd, d)
        elif master_fd in r:
            o = os.read(master_fd, 10240)
            if not prelude_passed:
                buf += o
                o = b""
                if b"READY" in buf:
                    o = buf[buf.rfind(b"READY") + 5:]
                    prelude_passed = True
            if o:
                os.write(sys.stdout.fileno(), o)

    # restore tty settings back
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_tty)
