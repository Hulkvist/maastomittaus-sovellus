"""Oikeat Trimble-mittausaineistot (tests/data/jobxml/, tests/data/lepolantie79.krd) eivät ole
julkisessa repossa, koska ne ovat työmittauksia. Niitä tarvitsevat testit on merkitty
@pytest.mark.oikeat_aineistot ja ohitetaan, jos aineistoja ei ole."""
import os

import pytest

JXL_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "jobxml")
OIKEAT_AINEISTOT = os.path.isdir(JXL_DATA)


def pytest_configure(config):
    config.addinivalue_line("markers", "oikeat_aineistot: tarvitsee tests/data/jobxml/-mittausaineistot")


def pytest_runtest_setup(item):
    if item.get_closest_marker("oikeat_aineistot") and not OIKEAT_AINEISTOT:
        pytest.skip("oikeat mittausaineistot (tests/data/jobxml/) puuttuvat")
