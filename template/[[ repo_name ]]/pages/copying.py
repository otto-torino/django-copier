"""The copy of a content block of a page, with its items and their files."""

from django.core.files.base import ContentFile
from django.db import models, transaction
from django.db.models import F
from django.utils.translation import gettext as _

from .models import PageContent


def _copy_files(instance):
    """Give the instance its own copy of every file: django-cleanup deletes
    the file of a record, which would vanish from a copy sharing its path."""
    for field in instance._meta.concrete_fields:
        if not isinstance(field, models.FileField):
            continue
        file = getattr(instance, field.attname)
        if not file:
            continue
        file.open("rb")
        try:
            content = file.read()
        finally:
            file.close()
        getattr(instance, field.attname).save(
            file.name.rsplit("/", 1)[-1], ContentFile(content), save=False
        )


def _items(block):
    """The records that belong to the block, as its cards or its images: the
    foreign keys to the type of the block, not those to every content block,
    as the block a column shows."""
    model = type(block)
    for relation in model._meta.related_objects:
        if relation.one_to_many and relation.field.remote_field.model is model:
            yield relation.field.name, list(getattr(block, relation.get_accessor_name()).all())


@transaction.atomic
def duplicate_block(content_block):
    """A copy of the block right after it, named as a copy, with copies of its
    items and of all the files."""
    block = content_block.content_object
    items = list(_items(block))
    position = content_block.position

    content_block.page.content_blocks.filter(position__gt=position).update(
        position=F("position") + 1
    )

    parent_link = block._meta.get_ancestor_link(PageContent)
    block.pk = None
    block.id = None
    setattr(block, parent_link.attname, None)
    block._state.adding = True
    block.object_id = None
    block.position = position + 1
    # the name in every language: with modeltranslation "name" stands for the
    # field of the active language, which would become a copy twice
    names = [field.attname for field in block._meta.concrete_fields if field.name.startswith("name_")]
    for attname in names or ["name"]:
        value = getattr(block, attname)
        if value:
            setattr(block, attname, _("%(name)s (copy)") % {"name": value})
    _copy_files(block)
    block.save()
    block.object_id = block.pk
    block.save()

    for field_name, records in items:
        for record in records:
            record.pk = None
            record.id = None
            record._state.adding = True
            setattr(record, field_name, block)
            _copy_files(record)
            record.save()
    return block
