"""Django Admin integration for NeoModel nodes."""

import logging

from django.contrib.admin import ModelAdmin
from django.http import HttpRequest

from neomodel.match_q import Q

from django_neomodel.dev import DjangoNeoNode


__all__ = ['DjangoNeoModelAdmin']


logger = logging.getLogger(__name__)


class DjangoNeoModelAdmin(ModelAdmin):
    """Base ModelAdmin class for NeoModel nodes.

    This class provides all the necessary overrides to make Django Admin work with NeoModel nodes.
    Subclasses should:
    1. Set `list_display`, `search_fields`, and `ordering` attributes
    2. Optionally override `get_queryset` if custom queryset logic is needed (default uses `self.model.objects.all()`)
    3. Optionally override `get_search_results` if custom search logic is needed

    The default `get_queryset` implementation uses `self.model.objects.all()` which is an alias
    for `self.model.nodes.all()` via the `DjangoNeoNode.objects` descriptor.
    """

    def has_add_permission(self, request: HttpRequest) -> bool:
        return True

    def has_change_permission(self,
                              request: HttpRequest,
                              obj: DjangoNeoNode | None = None) -> bool:
        return True

    def has_delete_permission(self,
                              request: HttpRequest,
                              obj: DjangoNeoNode | None = None) -> bool:
        return True

    def get_object(self, request, object_id, from_field=None):
        """Override to handle NeoModel nodes that use custom unique identifiers as pk.

        Django Admin's default get_object expects a queryset with a .model attribute,
        but NeoModel NodeSets don't have that. This override directly queries the
        NeoModel node by the class's _pk_field_name (e.g., uri, name, label).

        Note: NeoModel doesn't allow querying by element_id (it's an internal identifier),
        so we use the class's _pk_field_name attribute to determine which field to query.
        """
        try:
            # Get the pk field name from the model class
            pk_field_name = getattr(self.model, '_pk_field_name', None)
            if not pk_field_name:
                raise ValueError(f"{self.model.__name__} must set _pk_field_name class attribute (e.g., 'uri', 'name', 'label')")

            # object_id is the pk value (e.g., uri, name, label for NeoModel nodes)
            # Query directly using NeoModel's get method with the pk field
            obj = self.model.objects.get(**{pk_field_name: object_id})
            return obj
        except (self.model.DoesNotExist, Exception) as e:
            # NeoModel may raise DoesNotExist or other exceptions
            # Check if it's a "not found" type exception
            if 'not found' in str(e).lower() or 'does not exist' in str(e).lower():
                from django.http import Http404
                raise Http404(f"{self.model._meta.verbose_name} with pk={object_id} does not exist.")
            # For other exceptions, log and re-raise
            logger.error(f"Exception in {self.__class__.__name__}.get_object for {self.model.__name__}: {e}", exc_info=True, stack_info=True)
            raise

    def get_search_results(self, request, queryset, search_term):
        """Override to handle search using neomodel filters instead of Django Q objects.

        This default implementation handles search across all fields in `search_fields` using
        NeoModel's Q objects with OR logic. Subclasses can override for custom search behavior.
        """
        if search_term and self.search_fields:
            q_objects = []
            for field in self.search_fields:
                q_objects.append(Q(**{f"{field}__icontains": search_term}))
            # Combine with OR
            if q_objects:
                combined_q = q_objects[0]
                for q_obj in q_objects[1:]:
                    combined_q = combined_q | q_obj
                queryset = queryset.filter(combined_q)
        return queryset, False  # False = no distinct needed for NeoModel
