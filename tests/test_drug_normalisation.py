"""TR-37: unit tests for drug-name normalisation over >=10 real-world variants.

`normalize_drug_name` below is a Python mirror of the dbt macro
`dbt/macros/normalize_drug_name.sql` (TR-16). Keep the two in lock-step: same
steps, same salt list, same order. The macro is authoritative for the pipeline;
this test proves the logic is deterministic and covers the real variants FAERS
throws at it (dosage strings, salt forms, punctuation, casing).
"""
import re

import pytest

SALTS = [
    "HYDROCHLORIDE", "DIHYDROCHLORIDE", "HCL", "HYDROBROMIDE", "HBR", "SULFATE",
    "SULPHATE", "SODIUM", "DISODIUM", "POTASSIUM", "DIPOTASSIUM", "CALCIUM",
    "MAGNESIUM", "PHOSPHATE", "CITRATE", "TARTRATE", "BITARTRATE", "MESYLATE",
    "MESILATE", "MALEATE", "FUMARATE", "ACETATE", "SUCCINATE", "BESYLATE",
    "BESILATE", "MONOHYDRATE", "DIHYDRATE", "HEMIHYDRATE", "SESQUIHYDRATE",
    "HYDRATE", "ANHYDROUS", "MALATE", "NITRATE", "GLUCONATE", "LACTATE",
    "PAMOATE", "STEARATE", "PROPIONATE", "DIPROPIONATE", "FUROATE", "XINAFOATE",
    "TROMETHAMINE", "TROMETAMOL",
]
_DOSAGE = re.compile(
    r"[0-9]+([.,][0-9]+)?[ ]?(MG|MCG|UG|G|GM|KG|ML|L|IU|MEQ|MMOL|MOL|UNITS?|PERCENT|%)(/[A-Z]+)?"
)
_SALT = re.compile(r"[ ](" + "|".join(SALTS) + r")[ ]")


def normalize_drug_name(s: str | None) -> str:
    s = (s or "").upper()
    s = _DOSAGE.sub(" ", s)          # strip dosage strings
    s = re.sub(r"[^A-Z0-9 ]", " ", s)  # punctuation -> space
    s = f" {s} "                     # pad so first/last tokens can match
    s = _SALT.sub(" ", s)            # strip salt forms (two passes for adjacency)
    s = _SALT.sub(" ", s)
    return re.sub(r"[ ]+", " ", s).strip()


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Tylenol 500mg", "TYLENOL"),
        ("ACETAMINOPHEN 500 MG", "ACETAMINOPHEN"),
        ("Metformin Hydrochloride", "METFORMIN"),
        ("Metformin HCL 500mg", "METFORMIN"),
        ("Amlodipine Besylate 10mg", "AMLODIPINE"),
        ("Atorvastatin Calcium", "ATORVASTATIN"),
        ("Sertraline HCL", "SERTRALINE"),
        ("Metoprolol Tartrate", "METOPROLOL"),
        ("Fluticasone Furoate", "FLUTICASONE"),
        ("Omeprazole 20 mg/mL", "OMEPRAZOLE"),
        ("Insulin 100 IU", "INSULIN"),
        ("aspirin (acetylsalicylic acid)", "ASPIRIN ACETYLSALICYLIC ACID"),
        ("  lisinopril  ", "LISINOPRIL"),
        ("Amoxicillin/Clavulanate", "AMOXICILLIN CLAVULANATE"),
    ],
)
def test_known_variants(raw, expected):
    assert normalize_drug_name(raw) == expected


def test_none_and_empty():
    assert normalize_drug_name(None) == ""
    assert normalize_drug_name("") == ""
    assert normalize_drug_name("   ") == ""


def test_idempotent():
    for s in ["Metformin Hydrochloride 500mg", "Tylenol 500mg", "Insulin 100 IU"]:
        once = normalize_drug_name(s)
        assert normalize_drug_name(once) == once


def test_salt_variants_collapse_together():
    # the whole point: salt/dosage variants of one drug map to one identity
    assert (
        normalize_drug_name("Metformin Hydrochloride 850 mg")
        == normalize_drug_name("METFORMIN HCL")
        == normalize_drug_name("metformin")
    )
