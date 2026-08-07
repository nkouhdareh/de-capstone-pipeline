-- fails if the fact is implausibly small/large (smoke ~1.5M, full ~45M)
select count(*) as n
from {{ ref('fct_report_drug_reaction') }}
having count(*) < 100000 or count(*) > 200000000
