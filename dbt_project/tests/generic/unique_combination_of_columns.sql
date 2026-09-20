{#
    Test genérico propio: unicidad de una combinación de columnas.

    Equivale al de dbt_utils, pero escrito aquí para que el proyecto corra sin
    `dbt deps` (y por tanto sin red), que es un requisito de este repo: todo
    tiene que poder ejecutarse en local.
#}
{% test unique_combination_of_columns(model, combination_of_columns) %}

with validation as (

    select
        {{ combination_of_columns | join(', ') }},
        count(*) as n_records
    from {{ model }}
    group by {{ range(1, combination_of_columns | length + 1) | join(', ') }}
    having count(*) > 1

)

select * from validation

{% endtest %}
