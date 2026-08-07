with source as (
    select * from {{ source('raw', 'drug_ndc') }}
)
select
    v:product_ndc::varchar          as product_ndc,
    v:generic_name::varchar         as generic_name,
    v:brand_name::varchar           as brand_name,
    v:brand_name_base::varchar      as brand_name_base,
    v:product_type::varchar         as product_type,
    v:route::variant                as route,
    v:openfda.rxcui::array          as rxcui_arr,
    v:openfda.substance_name::array as substance_arr,
    v:active_ingredients::array     as active_ingredients
from source
