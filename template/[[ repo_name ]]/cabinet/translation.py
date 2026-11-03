from modeltranslation.translator import AlreadyRegistered, TranslationOptions, register
from pages.models import PageContent

from .models import AttachmentModel, PageContentMultiAttachment


try:

    @register(PageContent)
    class PageContentTranslationOptions(TranslationOptions):
        fields = ("name",)

except AlreadyRegistered:
    pass


@register(AttachmentModel)
class AttachmentModelTranslationOptions(TranslationOptions):
    # a different file per language, falling back to the default language one
    fields = ("file", "name", "description")


@register(PageContentMultiAttachment)
class PageContentMultiAttachmentTranslationOptions(TranslationOptions):
    pass
