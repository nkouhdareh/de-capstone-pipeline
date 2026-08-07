{% macro normalize_drug_name(col) -%}
{%- set salts = "HYDROCHLORIDE|DIHYDROCHLORIDE|HCL|HYDROBROMIDE|HBR|SULFATE|SULPHATE|SODIUM|DISODIUM|POTASSIUM|DIPOTASSIUM|CALCIUM|MAGNESIUM|PHOSPHATE|CITRATE|TARTRATE|BITARTRATE|MESYLATE|MESILATE|MALEATE|FUMARATE|ACETATE|SUCCINATE|BESYLATE|BESILATE|MONOHYDRATE|DIHYDRATE|HEMIHYDRATE|SESQUIHYDRATE|HYDRATE|ANHYDROUS|MALATE|NITRATE|GLUCONATE|LACTATE|PAMOATE|STEARATE|PROPIONATE|DIPROPIONATE|FUROATE|XINAFOATE|TROMETHAMINE|TROMETAMOL" -%}
trim(
  regexp_replace(
    regexp_replace(
      regexp_replace(
        ' ' || regexp_replace(
                 regexp_replace(
                   upper(coalesce({{ col }}, '')),
                   '[0-9]+([.,][0-9]+)?[ ]?(MG|MCG|UG|G|GM|KG|ML|L|IU|MEQ|MMOL|MOL|UNITS?|PERCENT|%)(/[A-Z]+)?', ' '
                 ),
                 '[^A-Z0-9 ]', ' '
               ) || ' ',
        '[ ]({{ salts }})[ ]', ' '
      ),
      '[ ]({{ salts }})[ ]', ' '
    ),
    '[ ]+', ' '
  )
)
{%- endmacro %}
