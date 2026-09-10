"""Phase 2, step 2: question sources grounded in the capstone's own FAERS output.

Two kinds of candidate, both drawn from the marts the capstone built:

1. VERIFY. Strong FAERS signals (drug, reaction) whose reaction term appears in
   that drug's label chunks. These become "Is REACTION listed on DRUG's label?"
   questions, the exact question BR-16 was written for.

2. NEGATIVE. Drugs that FAERS reports on but that have no label in the indexed
   corpus. A question about them cannot be answered from the corpus, which is
   what TR-55 and BR-17 require the system to recognise.

v2 fixes two problems the first run exposed:

- Confounding by indication. CERTOLIZUMAB PEGOL -> Rheumatoid arthritis came
  out as a top verify candidate. Rheumatoid arthritis is what the drug treats:
  FAERS lists it because the patients have it, and the label mentions it
  because the trials ran in those patients. It is the first artifact in the
  capstone README's "What this is not" table. v2 drops any pair whose reaction
  term appears in the drug's own indications.

- Name formats. Most first-run negatives were false: the drugs are in the
  corpus, written differently. Biosimilar suffixes (RISANKIZUMAB RZAA vs
  RISANKIZUMAB-RZAA), combinations (SULFAMETHOXAZOLE TRIMETHOPRIM vs
  SULFAMETHOXAZOLE AND TRIMETHOPRIM), salts mid-name (FLUTICASONE AND
  SALMETEROL vs FLUTICASONE PROPIONATE AND SALMETEROL). One row, AND OXYBATES,
  was the ADR-005 salt-stripping bug itself: calcium, magnesium, potassium and
  sodium oxybates with every salt removed. v2 compares the SET of significant
  words on both sides, with salt and filler words removed from both.

drug_key is never written out. Gold records anchor on set_id and label text,
per the Phase 1 constraint.

Outputs (gitignored, regenerable):
    data/rag/gold_verify_candidates.jsonl
    data/rag/gold_negative_candidates.jsonl

Usage:
    python -m rag.eval.signal_candidates
"""
from __future__ import annotations

import json
import time

import duckdb

OFFLINE = "D:/capstone/data/offline"
RAGDATA = "D:/capstone/data/rag"
SIGNALS = f"{OFFLINE}/sem_signal_metrics.parquet"
CHUNKS = f"{RAGDATA}/chunks.parquet"
OUT_VERIFY = f"{RAGDATA}/gold_verify_candidates.jsonl"
OUT_NEGATIVE = f"{RAGDATA}/gold_negative_candidates.jsonl"

SALT = "gold-v1"
MIN_CASES = 100          # well-evidenced pairs only
MIN_PRR = 3.0            # reported at least 3x more often than for other drugs
N_VERIFY = 40            # about 2x the verify questions we need
N_NEGATIVE = 30
MAX_PER_REACTION = 2     # stops one term (e.g. Dependence) filling the list

# MedDRA terms describing how a drug was used, not what it did to the patient.
NON_CLINICAL = ["off label", "product", "drug ineffective", "wrong", "use issue",
                "no adverse event", "intentional", "medication error", "exposure",
                "dose", "therapy", "treatment", "inappropriate", "interaction",
                "death", "condition aggravated", "general physical health",
                "device"]

# Names the ADR-005 normaliser produced by stripping salts. They are not drugs.
NOISE_DRUGS = ["CHLORIDE", "SODIUM", "POTASSIUM", "CALCIUM", "MAGNESIUM",
               "WATER", "DEXTROSE", "OXYGEN"]

# Removed from BOTH sides before comparing drug names, so salt forms, esters
# and filler words cannot make the same drug look like two different ones.
SALT_WORDS = ["HYDROCHLORIDE", "HCL", "HYDROBROMIDE", "HBR", "SODIUM",
              "POTASSIUM", "CALCIUM", "MAGNESIUM", "ZINC", "BROMIDE", "CHLORIDE",
              "SULFATE", "PHOSPHATE", "ACETATE", "CITRATE", "MALEATE",
              "FUMARATE", "SUCCINATE", "TARTRATE", "BITARTRATE", "MESYLATE",
              "BESYLATE", "TOSYLATE", "LACTATE", "GLUCONATE", "CARBONATE",
              "BICARBONATE", "NITRATE", "OXALATE", "PROPIONATE", "DIPROPIONATE",
              "FUROATE", "VALERATE", "TRIFENATATE", "XINAFOATE", "MONOHYDRATE",
              "DIHYDRATE", "HYDRATE", "ANHYDROUS", "DISODIUM", "ACID", "AND",
              "WITH", "TRIHYDRATE", "SESQUIHYDRATE", "DIETHYLAMINE", "EPOLAMINE"]

SAFETY_SECTIONS = ["adverse_reactions", "boxed_warning", "warnings_and_cautions",
                   "warnings", "otc_safety_panel"]

noise = ", ".join(f"'{n}'" for n in NOISE_DRUGS)
non_clinical = "|".join(NON_CLINICAL)
salt_list = "[" + ", ".join(f"'{w}'" for w in SALT_WORDS) + "]"
sections = ", ".join(f"'{s}'" for s in SAFETY_SECTIONS)


def name_tokens(col: str) -> str:
    """SQL for a drug name's significant words: uppercase, punctuation to spaces,
    salt and filler words dropped. RISANKIZUMAB-RZAA and RISANKIZUMAB RZAA both
    become [RISANKIZUMAB, RZAA]; FLUTICASONE PROPIONATE AND SALMETEROL becomes
    [FLUTICASONE, SALMETEROL]."""
    return (f"list_filter(regexp_split_to_array(trim(regexp_replace(upper({col}), "
            f"'[^A-Z0-9]+', ' ', 'g')), ' '), "
            f"w -> w <> '' AND NOT list_contains({salt_list}, w))")


CHUNK_NAMES = f"""
SELECT chunk_id, set_id, section, generic_name, brand_name, text,
       {name_tokens('generic_name')} AS tok,
       (generic_name NOT LIKE '%,%' AND upper(generic_name) NOT LIKE '% AND %') AS single
FROM '{CHUNKS}'
WHERE generic_name IS NOT NULL
  AND section IN ('indications_and_usage', {sections})
"""

STRONG = f"""
SELECT drug_name, reaction_pt, CAST(a AS BIGINT) AS cases, prr,
       {name_tokens('drug_name')} AS tok
FROM '{SIGNALS}'
WHERE is_signal_strict AND a >= {MIN_CASES} AND prr >= {MIN_PRR}
  AND length(reaction_pt) >= 5
  AND drug_name NOT IN ({noise})
  AND NOT regexp_matches(lower(reaction_pt), '{non_clinical}')
"""

# The "reaction" appears in the drug's own indications: often the disease being
# treated, reported because the patient has it. Confounding by indication.
IN_INDICATIONS = """
SELECT DISTINCT s.drug_name, s.reaction_pt, s.tok
FROM strong s
JOIN chunk_names c ON c.tok[1] = s.tok[1]
WHERE c.section = 'indications_and_usage'
  AND list_has_all(c.tok, s.tok)
  AND strpos(lower(c.text), lower(s.reaction_pt)) > 0
"""

# ...unless the label also puts it in a boxed warning, which makes it a side
# effect whatever else the label says. Clozapine's indications read "because
# of the risks of severe neutropenia ... use only in patients who have failed"
# other treatment: a risk restricting use, not the disease treated. v2 dropped
# it, filtering out the capstone's own acceptance signal.
TREATS = """
SELECT i.drug_name, i.reaction_pt
FROM in_indications i
WHERE NOT EXISTS (
    SELECT 1 FROM chunk_names b
    WHERE b.section = 'boxed_warning'
      AND b.tok[1] = i.tok[1] AND list_has_all(b.tok, i.tok)
      AND strpos(lower(b.text), lower(i.reaction_pt)) > 0)
"""

VERIFY = f"""
WITH side_effects AS (
    SELECT * FROM strong ANTI JOIN treats USING (drug_name, reaction_pt)
),
hits AS (
    SELECT s.drug_name, s.reaction_pt, s.cases, s.prr,
           c.chunk_id, c.set_id, c.section, c.generic_name, c.brand_name, c.text,
           strpos(lower(c.text), lower(s.reaction_pt)) AS pos
    FROM side_effects s
    JOIN chunk_names c ON c.tok[1] = s.tok[1]
    WHERE c.single AND c.section <> 'indications_and_usage'
      AND list_has_all(c.tok, s.tok)
      AND strpos(lower(c.text), lower(s.reaction_pt)) > 0
),
best_chunk AS (
    SELECT * FROM hits
    QUALIFY row_number() OVER (
        PARTITION BY drug_name, reaction_pt
        ORDER BY (section = 'adverse_reactions') DESC, md5(chunk_id || '{SALT}')) = 1
),
one_per_drug AS (
    SELECT * FROM best_chunk
    QUALIFY row_number() OVER (
        PARTITION BY drug_name ORDER BY cases DESC, reaction_pt) = 1
),
diverse AS (
    SELECT * FROM one_per_drug
    QUALIFY row_number() OVER (
        PARTITION BY lower(reaction_pt) ORDER BY cases DESC, drug_name) <= {MAX_PER_REACTION}
)
SELECT drug_name, reaction_pt, cases, round(prr, 2) AS prr,
       chunk_id, set_id, section, generic_name, brand_name,
       substr(text, pos, length(reaction_pt))       AS answer_span,
       substr(text, greatest(pos - 160, 1), 360)    AS context
FROM diverse
ORDER BY cases DESC, drug_name
LIMIT {N_VERIFY}
"""

FAERS_TOK = f"""
SELECT drug_name,
       CAST(sum(a) AS BIGINT) AS cases,
       arg_max(reaction_pt, a) FILTER (
           WHERE NOT regexp_matches(lower(reaction_pt), '{non_clinical}')) AS top_reaction,
       {name_tokens('drug_name')} AS tok
FROM '{SIGNALS}'
WHERE drug_name NOT IN ({noise})
GROUP BY drug_name
"""

# A FAERS drug is present if some label name contains all of its significant
# words. Blocking on the first word keeps this a join, not a cross product.
PRESENT = f"""
WITH label_tok AS (
    SELECT DISTINCT {name_tokens('n')} AS tok
    FROM (SELECT generic_name AS n FROM '{CHUNKS}' WHERE generic_name IS NOT NULL
          UNION
          SELECT brand_name FROM '{CHUNKS}' WHERE brand_name IS NOT NULL)
),
label_index AS (SELECT tok, unnest(tok) AS word FROM label_tok)
SELECT DISTINCT f.drug_name
FROM faers_tok f
JOIN label_index li ON li.word = f.tok[1]
WHERE list_has_all(li.tok, f.tok)
"""

NEGATIVE = f"""
SELECT drug_name, cases, top_reaction
FROM faers_tok
WHERE len(tok) > 0 AND top_reaction IS NOT NULL
  AND drug_name NOT IN (SELECT drug_name FROM present)
ORDER BY cases DESC, drug_name
LIMIT {N_NEGATIVE}
"""


def write(path: str, prefix: str, cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    with open(path, "w", encoding="utf-8") as fh:
        for i, row in enumerate(rows, start=1):
            fh.write(json.dumps({f"{prefix}_id": f"{prefix[0]}{i:03d}", **row},
                                ensure_ascii=False) + "\n")
    return rows


def count(con, sql: str) -> int:
    return con.execute(sql).fetchone()[0]


def main() -> None:
    con = duckdb.connect()
    t0 = time.time()

    con.execute(f"CREATE TEMP TABLE chunk_names AS {CHUNK_NAMES}")
    con.execute(f"CREATE TEMP TABLE strong AS {STRONG}")
    con.execute(f"CREATE TEMP TABLE in_indications AS {IN_INDICATIONS}")
    con.execute(f"CREATE TEMP TABLE treats AS {TREATS}")
    n_strong = count(con, "SELECT count(*) FROM strong WHERE len(tok) > 0")
    n_mentioned = count(con, "SELECT count(*) FROM in_indications")
    n_treats = count(con, "SELECT count(*) FROM treats")
    verify = write(OUT_VERIFY, "vcand", con.execute(VERIFY))

    print(f"strong clinical FAERS signals (>= {MIN_CASES} cases, PRR >= {MIN_PRR}): {n_strong:,}")
    print(f"  reaction also named in the drug's own indications: {n_mentioned:,}")
    print(f"    kept, because the label has it in a boxed warning: {n_mentioned - n_treats:,}")
    print(f"    dropped as the disease the drug treats: {n_treats:,}")
    print(f"VERIFY: {len(verify)} candidates -> {OUT_VERIFY}  ({time.time()-t0:.0f}s)\n")
    for r in verify[:10]:
        print(f"  {r['drug_name']:<22} {r['reaction_pt']:<28} "
              f"{r['cases']:>6,} cases  PRR {r['prr']:>7}  [{r['section']}]")
    for r in verify[:2]:
        print(f"\n  context, {r['drug_name']} / {r['reaction_pt']}:\n  ...{r['context']}...")

    t1 = time.time()
    con.execute(f"CREATE TEMP TABLE faers_tok AS {FAERS_TOK}")
    con.execute(f"CREATE TEMP TABLE present AS {PRESENT}")
    n_checked = count(con, "SELECT count(*) FROM faers_tok WHERE len(tok) > 0")
    n_present = count(con, "SELECT count(*) FROM present")
    negative = write(OUT_NEGATIVE, "ncand", con.execute(NEGATIVE))

    print(f"\nFAERS drugs checked: {n_checked:,}   found in corpus: {n_present:,}   "
          f"not found: {n_checked - n_present:,}")
    print(f"NEGATIVE: {len(negative)} candidates -> {OUT_NEGATIVE}  ({time.time()-t1:.0f}s)\n")
    for r in negative[:20]:
        print(f"  {r['drug_name']:<34} {r['cases']:>8,} cases   top reaction: {r['top_reaction']}")


if __name__ == "__main__":
    main()
