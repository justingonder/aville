# {{ biz.name }}

{% if biz.metadata and biz.metadata.description %}{{ biz.metadata.description }}
{% endif %}
{% if biz.address %}**Address:** {{ biz.address }}
{% endif %}{% if biz.metadata and biz.metadata.telephone %}**Phone:** {{ biz.metadata.telephone }}
{% endif %}{% if biz.website %}**Website:** {{ biz.website }}
{% endif %}{% if biz.metadata and biz.metadata.price_range %}**Price range:** {{ biz.metadata.price_range }}
{% endif %}{% if biz.metadata and biz.metadata.same_as %}**Social:** {% for url in biz.metadata.same_as %}<{{ url }}>{% if not loop.last %}, {% endif %}{% endfor %}
{% endif %}

{% if biz.hours %}## Hours

{% for day_key, day_name in [('mon','Monday'),('tue','Tuesday'),('wed','Wednesday'),('thu','Thursday'),('fri','Friday'),('sat','Saturday'),('sun','Sunday')] %}- **{{ day_name }}:** {% if biz.hours.get(day_key) %}{{ fmt_hours_range(biz.hours[day_key]) }}{% else %}Closed{% endif %}
{% endfor %}
{% endif %}
{% if upcoming_dated %}## Coming up

{% for ev in upcoming_dated %}- [{{ ev.title }}]({{ site_url }}/event/{{ ev.id }}/) — {{ when_text(ev) }}
{% endfor %}
{% endif %}
{% if weekly_regulars %}## Weekly regulars

{% for ev in weekly_regulars %}- [{{ ev.title }}]({{ site_url }}/event/{{ ev.id }}/) — {{ when_text(ev) }}
{% endfor %}
{% endif %}
{% if recent_flyers %}## Recent flyers

{% for ev in recent_flyers %}- [{{ ev.title }}]({{ site_url }}/event/{{ ev.id }}/) — {{ when_text(ev) }}
{% endfor %}
{% endif %}
---

- Canonical URL: {{ site_url }}/business/{{ biz.slug }}/
- HTML version: {{ site_url }}/business/{{ biz.slug }}/
- Back to event listing: {{ site_url }}/
