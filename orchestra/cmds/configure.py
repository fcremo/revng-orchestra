from loguru import logger

from ..executor import Executor
from ..model.configuration import Configuration


def install_subcommand(sub_argparser):
    cmd_parser = sub_argparser.add_parser("configure", handler=handle_configure, help="Run configure script")
    cmd_parser.add_argument("component")
    cmd_parser.add_argument("--no-deps", action="store_true", help="Only execute the requested action")


def handle_configure(args):
    config = Configuration(args)
    build = config.get_build(args.component)

    if not build:
        suggested_component_name = config.get_suggested_component_name(args.component)
        logger.error(f"Component {args.component} not found! Did you mean {suggested_component_name}?")
        exit(1)

    executor = Executor(args, [build.configure], no_deps=args.no_deps)
    failed = executor.run()

    exitcode = 1 if failed else 0
    exit(exitcode)
