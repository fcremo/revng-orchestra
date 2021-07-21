import os
import re
from pathlib import Path
from typing import Optional, Union

from ..actions.util import get_subprocess_output, try_get_subprocess_output, run_internal_subprocess
from ..exceptions import InternalException, InternalCommandException


def run_git(
    *args,
    workdir: Optional[Union[str, Path]] = None,
):
    """Run a git command. Raises an InternalSubprocessException if git returns a non-zero exit code.
    :param workdir: Git behaves as if it was invoked in this working directory (optional)
    """
    git_cmd = [
        "git",
    ]
    if workdir:
        git_cmd.append("-C")
        git_cmd.append(str(workdir))
    git_cmd.extend(args)

    return run_internal_subprocess(git_cmd)


def ls_remote(remote):
    env = os.environ.copy()
    env["GIT_SSH_COMMAND"] = "ssh -oControlPath=~/.ssh/ssh-mux-%r@%h:%p -oControlMaster=auto -o ControlPersist=10"
    env["GIT_ASKPASS"] = "/bin/true"
    result = try_get_subprocess_output(["git", "ls-remote", "-h", "--refs", remote], environment=env)
    if result is None:
        return {}

    parse_regex = re.compile(r"(?P<commit>[a-f0-9]*)\W*refs/heads/(?P<branch>.*)")

    return {branch: commit for commit, branch in parse_regex.findall(result)}


def current_branch_info(repo_path):
    try:
        branch_name = get_subprocess_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path).strip()
        commit = get_subprocess_output(["git", "rev-parse", "HEAD"], cwd=repo_path).strip()
        return branch_name, commit
    except InternalCommandException:
        return None, None


def is_root_of_git_repo(path):
    """Returns true if the given path is the root of a git repository (it contains a .git directory)"""
    return os.path.exists(path) and ".git" in os.listdir(path)


def get_worktree_root(absolute_path_to_file_in_worktree: Union[str, Path]) -> Path:
    """Returns the root of a git worktree given the absolute path to a file in the worktree.
    The worktree must be a "canonical" clone, e.g. the root is the directory containing the .git repository directory"""
    absolute_path_to_file_in_worktree = Path(absolute_path_to_file_in_worktree)
    assert absolute_path_to_file_in_worktree.is_absolute()
    root_path = Path("/")
    while absolute_path_to_file_in_worktree != root_path:
        if (absolute_path_to_file_in_worktree / ".git").exists():
            return absolute_path_to_file_in_worktree
        absolute_path_to_file_in_worktree = absolute_path_to_file_in_worktree.parent

    # Edge case: the root contains the git repo
    if (absolute_path_to_file_in_worktree / ".git").exists():
        return absolute_path_to_file_in_worktree

    raise InternalException(f"{absolute_path_to_file_in_worktree} is not inside a git worktree")
