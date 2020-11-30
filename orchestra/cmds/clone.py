from loguru import logger

from ..executor import Executor
from ..model.configuration import Configuration


def install_subcommand(sub_argparser):
    cmd_parser = sub_argparser.add_parser("clone", handler=handle_clone, help="Clone a component")
    cmd_parser.add_argument("component")


def handle_clone(args):
    config = Configuration(args)
    build = config.get_build(args.component)

    if not build:
        suggested_component_name = config.get_suggested_component_name(args.component)
        logger.error(f"Component {args.component} not found! Did you mean {suggested_component_name}?")
        exit(1)

    if not build.component.clone:
        print("This component does not have a git repository configured!")
        return

    executor = Executor(args, [build.clone])
    failed = executor.run()

    exitcode = 1 if failed else 0
    exit(exitcode)
