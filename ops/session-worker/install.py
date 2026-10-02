"""Install the reviewed session worker using the existing pinned-release installer."""

import argparse
import importlib.util
from pathlib import Path
import sys


def installer():
    spec = importlib.util.spec_from_file_location("editorial_installer", Path(__file__).parents[1] / "editorial-worker/install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def service_definition(release, state, home, config):
    module = installer()
    module.LABEL = "place.panther.session-worker"
    result = module.service_definition(release, state, home)
    result["ProgramArguments"] = [str(release / "venv/bin/panther"), "recording", "automation", "worker",
                                  "--config", str(config), "--work-dir", str(state / "jobs"), "--once"]
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--state-dir", type=Path, default=Path.home() / "Library/Application Support/Panther/session-worker")
    parser.add_argument("--start", action="store_true")
    args = parser.parse_args()
    # Validate configuration using the checkout interpreter before installing.
    sys.path.insert(0, str(args.repo / "src"))
    from panther_journal.session_worker import settings
    settings(args.config)
    module = installer()
    module.LABEL = "place.panther.session-worker"
    module.service_definition = lambda release, state, home: service_definition(release, state, home, args.config.resolve())
    module.install(args.repo, args.state_dir, args.start)
