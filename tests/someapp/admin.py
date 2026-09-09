from django.contrib import admin as dj_admin
from django.contrib.admin import register
from django_neomodel.admin import DjangoNeoModelAdmin
from .models import Library, Book, Shelf


class LibraryAdmin(dj_admin.ModelAdmin):
    list_display = (
        "id",
        "name",
    )
dj_admin.site.register(Library, LibraryAdmin)


@register(Book)
class BookAdmin(DjangoNeoModelAdmin):
    list_display = ("title", "created")


@register(Shelf)
class ShelfAdmin(DjangoNeoModelAdmin):
    list_display = ("name",)
