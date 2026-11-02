"""Pieni Streamlit-sovellus muokkauskartan selaintestiin (test_selain_muokkain.py): yksi avoin viiva ja
pisteet, kartan tapahtumat näytetään JSON-listana. Viiva ei muutu tapahtumista, joten kohteet pysyvät
paikallaan."""
import json
import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import seinalinjan_muokkain as slm

E0, N0 = 25497130.0, 6677370.0
KARJET = [(0, 0), (20, 0), (20, 10), (0, 10)]
PISTEET = [(str(i + 1), "RAK 5", E0 + x, N0 + y, None) for i, (x, y) in enumerate(KARJET)] + \
    [("P9", "RAK 5", E0 + 23, N0 + 4, None)]
TULOS = {"viivat": [{"nimi": "Viiva 1", "suljettu": False,
                     "karjet": [{"e": E0 + x, "n": N0 + y, "z": None, "nimi": str(i + 1), "laji": "mitattu"}
                                for i, (x, y) in enumerate(KARJET)]}]}

if __name__ == "__main__":         # streamlit run; testi tuo vain vakiot
    st.set_page_config(layout="wide")             # kuten app.py
    tapahtumat = st.session_state.setdefault("tapahtumat", [])
    t = slm.nayta(TULOS, PISTEET, kumottavia=len(tapahtumat))
    if t:
        tapahtumat.append(t)
        st.rerun()                                # kuten app.py: kartta saa uuden tilan (Kumoa-nappi)
    st.code(json.dumps(tapahtumat, ensure_ascii=False), language=None)
