{% macro metric_prr(a, b, c, d) -%}
( (({{ a }})::float / nullif((({{ a }})::float + ({{ b }})::float), 0))
  / nullif( (({{ c }})::float / nullif((({{ c }})::float + ({{ d }})::float), 0)), 0) )
{%- endmacro %}

{% macro metric_ror(a, b, c, d) -%}
( (({{ a }})::float * ({{ d }})::float) / nullif( (({{ b }})::float * ({{ c }})::float), 0) )
{%- endmacro %}

{% macro metric_ror_ci_lower(a, b, c, d) -%}
exp( ln( nullif( {{ metric_ror(a, b, c, d) }}, 0) )
  - 1.96 * sqrt( 1.0/nullif(({{ a }})::float,0) + 1.0/nullif(({{ b }})::float,0)
               + 1.0/nullif(({{ c }})::float,0) + 1.0/nullif(({{ d }})::float,0) ) )
{%- endmacro %}

{% macro metric_chi2_yates(a, b, c, d) -%}
{%- set n = "((" ~ a ~ ")::float + (" ~ b ~ ")::float + (" ~ c ~ ")::float + (" ~ d ~ ")::float)" -%}
( {{ n }} * power( abs(({{ a }})::float * ({{ d }})::float - ({{ b }})::float * ({{ c }})::float) - {{ n }}/2.0, 2)
  / nullif( (({{ a }})::float + ({{ b }})::float) * (({{ c }})::float + ({{ d }})::float)
          * (({{ a }})::float + ({{ c }})::float) * (({{ b }})::float + ({{ d }})::float), 0) )
{%- endmacro %}
