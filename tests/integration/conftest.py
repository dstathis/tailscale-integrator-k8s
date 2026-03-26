# Copyright 2026 Dylan Stephano-Shachter
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# See LICENSE file for licensing details.
#
# The integration tests use the Jubilant library. See https://documentation.ubuntu.com/jubilant/

import logging
import os
import pathlib
import subprocess
import sys
import time

import jubilant
import pytest

logger = logging.getLogger(__name__)

TESTERS_DIR = pathlib.Path(__file__).parent / "testers"


@pytest.fixture(scope="module")
def juju(request: pytest.FixtureRequest):
    """Create a temporary Juju model for running tests."""
    with jubilant.temp_model() as juju:
        yield juju

        if request.session.testsfailed:
            logger.info("Collecting Juju logs...")
            time.sleep(0.5)
            log = juju.debug_log(limit=1000)
            print(log, end="", file=sys.stderr)


@pytest.fixture(scope="session")
def charm():
    """Return the path of the charm under test."""
    if "CHARM_PATH" in os.environ:
        charm_path = pathlib.Path(os.environ["CHARM_PATH"])
        if not charm_path.exists():
            raise FileNotFoundError(f"Charm does not exist: {charm_path}")
        return charm_path
    # Look for a .charm file in the project directory.
    project_dir = pathlib.Path(__file__).parents[2]
    charms = sorted(project_dir.glob("*.charm"))
    if not charms:
        raise FileNotFoundError(f"No .charm file found in {project_dir}")
    return charms[-1]


def _build_tester(name: str) -> pathlib.Path:
    """Build a tester charm and return the path to the .charm file."""
    tester_dir = TESTERS_DIR / name
    if not tester_dir.exists():
        raise FileNotFoundError(f"Tester charm directory does not exist: {tester_dir}")
    subprocess.run(["charmcraft", "pack"], cwd=tester_dir, check=True)
    charms = sorted(tester_dir.glob("*.charm"))
    if not charms:
        raise FileNotFoundError(f"No .charm file found after build in {tester_dir}")
    return charms[-1]


@pytest.fixture(scope="session")
def ingress_requirer_charm():
    """Build and return the path to the ingress-requirer tester charm."""
    return _build_tester("ingress-requirer")
