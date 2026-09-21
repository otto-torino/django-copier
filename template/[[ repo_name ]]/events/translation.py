from modeltranslation.translator import TranslationOptions, register

from .models import Event


@register(Event)
class EventTranslationOptions(TranslationOptions):
    fields = (
        "title",
        "abstract",
        "description",
        "alt_text",
        "location",
        "meta_title",
        "meta_description",
    )
