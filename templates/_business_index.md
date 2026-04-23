# All venues — A'ville.net

{{ businesses | length }} bars, restaurants, theaters, cafes, and arts venues in Andersonville, Chicago. Each has a canonical entity page at `{{ site_url }}/business/{slug}/` with `LocalBusiness` JSON-LD, hours, and current events.

{% for biz in businesses %}
## [{{ biz.name }}]({{ site_url }}/business/{{ biz.slug }}/)

- **Category:** {{ biz.category | capitalize }}{% if biz.subcategory %} · {{ biz.subcategory | replace('-', ' ') }}{% endif %}
{% if biz.address %}- **Address:** {{ biz.address }}
{% endif %}{% if biz.website %}- **Website:** {{ biz.website }}
{% endif %}{% if biz.metadata and biz.metadata.description %}
{{ biz.metadata.description }}
{% endif %}
{% endfor %}
