import glob
import logging
import os
from collections import OrderedDict
from textwrap import dedent

from .action import Action
from .util import run_script
from ..util import is_installed, get_installed_build


class InstallAction(Action):
    def __init__(self, build, script, config):
        super().__init__("install", build, script, config)

    def _run(self, show_output=False, args=None):
        environment = self.config.global_env()
        tmp_root = environment["TMP_ROOT"]
        orchestra_root = environment['ORCHESTRA_ROOT']

        logging.info("Preparing temporary root directory")
        self._prepare_tmproot()
        pre_file_list = self._index_directory(tmp_root + orchestra_root, strip_prefix=tmp_root + orchestra_root)

        logging.info("Executing install script")
        run_script(self.script, show_output=show_output, environment=self.environment)

        # TODO: maybe this should be put into the configuration and not in Orchestra itself
        logging.info("Converting hardlinks to symbolic")
        self._hard_to_symbolic(show_output)

        # TODO: maybe this should be put into the configuration and not in Orchestra itself
        logging.info("Fixing RPATHs")
        self._fix_rpath(show_output)

        # TODO: this should be put into the configuration and not in Orchestra itself
        logging.info("Replacing NDEBUG preprocessor statements")
        self._replace_ndebug(True, show_output)

        post_file_list = self._index_directory(tmp_root + orchestra_root, strip_prefix=tmp_root + orchestra_root)
        new_files = [f for f in post_file_list if f not in pre_file_list]

        if not args.no_merge:
            logging.info("Cleaning up previous installation (if present)")
            self._uninstall_currently_installed_build(show_output)

            logging.info("Merging installation into Orchestra root directory")
            self._merge(show_output)

            # Write file index
            os.makedirs(self.config.component_index_dir(), exist_ok=True)
            installed_component_path = self.config.component_index_path(self.build.component.name)
            with open(installed_component_path, "w") as f:
                f.truncate(0)
                f.write(self.build.qualified_name + "\n")
                f.write("\n".join(new_files))

    def _is_satisfied(self):
        return is_installed(self.config, self.build.component.name, wanted_build=self.build.name)

    def _prepare_tmproot(self):
        script = dedent("""
        rm -rf "$TMP_ROOT"
        mkdir -p "$TMP_ROOT"
        mkdir -p "${TMP_ROOT}${ORCHESTRA_ROOT}/include"
        mkdir -p "${TMP_ROOT}${ORCHESTRA_ROOT}/lib64"{,/include,/pkgconfig}
        test -e "${TMP_ROOT}${ORCHESTRA_ROOT}/lib" || ln -s lib64 "${TMP_ROOT}${ORCHESTRA_ROOT}/lib"
        test -L "${TMP_ROOT}${ORCHESTRA_ROOT}/lib"
        mkdir -p "${TMP_ROOT}${ORCHESTRA_ROOT}/bin"
        mkdir -p "${TMP_ROOT}${ORCHESTRA_ROOT}/usr/"{lib,include}
        mkdir -p "${TMP_ROOT}${ORCHESTRA_ROOT}/share/"{info,doc,man}
        touch "${TMP_ROOT}${ORCHESTRA_ROOT}/share/info/dir"
        mkdir -p "${TMP_ROOT}${ORCHESTRA_ROOT}/libexec"
        """)
        run_script(script, environment=self.environment)

    def _hard_to_symbolic(self, show_output):
        hard_to_symbolic = """hard-to-symbolic.py "${TMP_ROOT}${ORCHESTRA_ROOT}" """
        run_script(hard_to_symbolic, show_output=show_output, environment=self.environment)

    def _fix_rpath(self, show_output):
        fix_rpath_script = dedent(f"""
            cd "$TMP_ROOT$ORCHESTRA_ROOT"
            # Fix rpath
            find . -type f -executable | while read EXECUTABLE; do
                if head -c 4 "$EXECUTABLE" | grep '^.ELF' > /dev/null &&
                        file "$EXECUTABLE" | grep x86-64 | grep -E '(shared|dynamic)' > /dev/null;
                then
                    REPLACE='$'ORIGIN/$(realpath --relative-to="$(dirname "$EXECUTABLE")" ".")
                    echo "Setting rpath of $EXECUTABLE to $REPLACE"
                    elf-replace-dynstr.py "$EXECUTABLE" "$RPATH_PLACEHOLDER" "$REPLACE" /
                    elf-replace-dynstr.py "$EXECUTABLE" "$ORCHESTRA_ROOT" "$REPLACE" /
                fi
            done
            """)
        run_script(fix_rpath_script, show_output=show_output, environment=self.environment)

    def _replace_ndebug(self, enable_debugging, show_output):
        debug, ndebug = ("1", "0") if enable_debugging else ("0", "1")
        patch_ndebug_script = dedent(rf"""
                cd "$TMP_ROOT$ORCHESTRA_ROOT"
                find include/ -name "*.h" \
                  -exec \
                    sed -i \
                    -e 's|^\s*#\s*ifndef\s\+NDEBUG|#if {debug}|' \
                    -e 's|^\s*#\s*ifdef\s\+NDEBUG|#if {ndebug}|' \
                    -e 's|^\(\s*#\s*if\s\+.*\)!defined(NDEBUG)|\1{debug}|' \
                    -e 's|^\(\s*#\s*if\s\+.*\)defined(NDEBUG)|\1{ndebug}|' \
                    {"{}"} ';'
                """)
        run_script(patch_ndebug_script, show_output=show_output, environment=self.environment)

    def _uninstall_currently_installed_build(self, show_output):
        installed_build = get_installed_build(self.build.component.name, self.config)

        if installed_build is None:
            return

        uninstall(self.build.component.name, self.config)

    def _merge(self, show_output):
        copy_command = f'cp -farl "$TMP_ROOT/$ORCHESTRA_ROOT/." "$ORCHESTRA_ROOT"'
        run_script(copy_command, show_output=show_output, environment=self.environment)

    @staticmethod
    def _index_directory(dirpath, strip_prefix=None):
        paths = list(glob.glob(f"{dirpath}/**", recursive=True))
        if strip_prefix:
            paths = [remove_prefix(p, strip_prefix) for p in paths]
        return paths

    @property
    def environment(self) -> OrderedDict:
        env = super().environment
        env["DESTDIR"] = env["TMP_ROOT"]
        return env

    def _implicit_dependencies(self):
        return {self.build.configure}


class InstallAnyBuildAction(Action):
    def __init__(self, build, config):
        installed_build_name = get_installed_build(build.component.name, config)
        if installed_build_name:
            chosen_build = build.component.builds[installed_build_name]
        else:
            chosen_build = build
        super().__init__("install any", chosen_build, None, config)
        self._original_build = build

    def _implicit_dependencies(self):
        return {self.build.install}

    def _run(self, show_output=False, args=None):
        return

    def is_satisfied(self, recursively=False, already_checked=None):
        return self.build.install.is_satisfied(recursively=recursively, already_checked=already_checked)

    def _is_satisfied(self):
        raise NotImplementedError("This method should not be called!")

    @property
    def name_for_graph(self):
        if self.build == self._original_build:
            return f"install {self.build.component.name} (prefer {self._original_build.name})"
        else:
            return f"install {self.build.component.name} (prefer {self._original_build.name}, chosen {self.build.name})"

    @property
    def name_for_components(self):
        return f"{self._original_build.component.name}~{self._original_build.name}"


def remove_prefix(string, prefix):
    if string.startswith(prefix):
        return string[len(prefix):]
    else:
        return string[:]


def uninstall(component_name, config):
    index_path = config.component_index_path(component_name)
    with open(index_path) as f:
        f.readline()
        paths = f.readlines()

    # Ensure depth first visit by reverse-sorting
    paths.sort(reverse=True)
    paths = [path.strip() for path in paths]

    for path in paths:
        path = path.lstrip("/")
        path_to_delete = os.path.join(config.global_env()['ORCHESTRA_ROOT'], path)
        if os.path.isfile(path_to_delete) or os.path.islink(path_to_delete):
            logging.debug(f"Deleting {path_to_delete}")
            os.remove(path_to_delete)
        elif os.path.isdir(path_to_delete):
            if os.listdir(path_to_delete):
                logging.debug(f"Not removing directory {path_to_delete} as it is not empty")
            else:
                logging.debug(f"Deleting directory {path_to_delete}")
                os.rmdir(path_to_delete)

    logging.debug(f"Deleting index file {index_path}")
    os.remove(index_path)