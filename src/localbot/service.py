from __future__ import annotations

import os

from localbot.config import load_config
from localbot.litellm_builder import provider_runtime_env
from localbot.paths import load_env_files, resolve_config_path
from localbot.proxy_manager import _proxy_command


def main() -> None:
    load_env_files()
    config = load_config(resolve_config_path())
    master_key = os.environ.get(config.proxy.master_key_env)
    if not master_key:
        raise SystemExit(f"Missing {config.proxy.master_key_env}")

    env = os.environ.copy()
    env.update(provider_runtime_env(config))
    command = _proxy_command(config, master_key)
    os.execvpe(command[0], command, env)


if __name__ == "__main__":
    main()
