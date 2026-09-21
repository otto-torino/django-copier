from modeltranslation.translator import TranslationOptions, register

from .models import NewsArticle


@register(NewsArticle)
class NewsArticleTranslationOptions(TranslationOptions):
    fields = (
        "title",
        "abstract",
        "content",
        "alt_text",
        "meta_title",
        "meta_description",
    )
