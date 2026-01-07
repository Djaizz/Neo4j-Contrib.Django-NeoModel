"""Django Admin integration for NeoModel nodes."""

import logging
import traceback
from io import StringIO

from django.contrib.admin import ModelAdmin
from django.http import HttpRequest, HttpResponse
from django.utils.html import format_html

from neomodel.match_q import Q

from . import DjangoNode


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
    for `self.model.nodes.all()` via the `DjangoNode.objects` descriptor.
    """

    def has_add_permission(self, request: HttpRequest) -> bool:
        return True

    def has_change_permission(self,
                              request: HttpRequest,
                              obj: DjangoNode | None = None) -> bool:
        return True

    def has_delete_permission(self,
                              request: HttpRequest,
                              obj: DjangoNode | None = None) -> bool:
        return True

    def has_view_permission(self,
                            request: HttpRequest,
                            obj: DjangoNode | None = None) -> bool:
        """Return True if the given request has permission to view the given model instance.

        This is required for Django Admin's changelist_view, which checks
        has_view_or_change_permission, which in turn calls has_view_permission.
        """
        return True

    def has_view_or_change_permission(self,
                                      request: HttpRequest,
                                      obj: DjangoNode | None = None) -> bool:
        """Return True if the request has permission to view or change the model instance.

        This is checked by changelist_view before displaying the changelist.
        """
        return self.has_view_permission(request, obj) or self.has_change_permission(request, obj)

    def get_queryset(self, request):
        """Return a queryset for use in Django Admin.

        This ensures we return a properly initialized NodeSet from the model's objects manager.
        Override to catch errors during queryset creation.
        """
        try:
            return self.model.objects.all()
        except Exception as e:
            # Log the full error with traceback
            logger.error(
                f"Error in {self.__class__.__name__}.get_queryset for {self.model.__name__}: {e}",
                exc_info=True,
                stack_info=True
            )
            # Print to stderr for immediate visibility (always shows)
            import sys
            print("=" * 80, file=sys.stderr)
            print("=" * 80, file=sys.stderr)
            print(f"ERROR in {self.__class__.__name__}.get_queryset for {self.model.__name__}:", file=sys.stderr)
            print(f"Exception type: {type(e).__name__}", file=sys.stderr)
            print(f"Exception message: {e}", file=sys.stderr)
            print("\nFull traceback:", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            print("=" * 80, file=sys.stderr)
            print("=" * 80, file=sys.stderr)
            # Re-raise to show actual error
            raise

    def get_object(self, request, object_id, from_field=None):
        """Override to handle NeoModel nodes that use custom unique identifiers as pk.

        Django Admin's default get_object expects a queryset with a .model attribute,
        but NeoModel NodeSets don't have that. This override directly queries the
        NeoModel node by the field marked with primary_key=True.

        Note: NeoModel doesn't allow querying by element_id (it's an internal identifier),
        so we use the field marked with primary_key=True to determine which field to query.
        """
        try:
            # Get the pk field from the model class (set by DjangoNode._meta)
            pk_prop = getattr(self.model, 'pk', None)
            if not pk_prop:
                raise ValueError(f"{self.model.__name__} must have a field with primary_key=True")

            # Get the field name from the pk property
            pk_field_name = pk_prop.name

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
        if search_term and self.search_fields and len(self.search_fields) > 0:
            # Build a single Q object with OR conditions for all search fields
            # NeoModel's q_filters is a single Q object, not a list
            if len(self.search_fields) == 1:
                # Single field - create Q object directly
                field = self.search_fields[0]
                search_q = Q(**{f"{field}__icontains": search_term})
            else:
                # Multiple fields - combine with OR using | operator
                # Start with first field, then OR with each subsequent field
                search_q = Q(**{f"{self.search_fields[0]}__icontains": search_term})
                for field in self.search_fields[1:]:
                    search_q = search_q | Q(**{f"{field}__icontains": search_term})

            # Apply the combined Q filter to the queryset
            # NeoModel's filter() will AND this with existing q_filters
            queryset = queryset.filter(search_q)
        return queryset, False  # False = no distinct needed for NeoModel

    def get_changelist(self, request, **kwargs):
        """Return the ChangeList class for use on the changelist page.

        Override to catch errors during ChangeList instantiation.
        """
        try:
            return super().get_changelist(request, **kwargs)
        except Exception as e:
            # Log the full error with traceback
            logger.error(
                f"Error in {self.__class__.__name__}.get_changelist for {self.model.__name__}: {e}",
                exc_info=True,
                stack_info=True
            )
            # Print to stderr for immediate visibility (always shows)
            import sys
            print("=" * 80, file=sys.stderr)
            print("=" * 80, file=sys.stderr)
            print(f"ERROR in {self.__class__.__name__}.get_changelist for {self.model.__name__}:", file=sys.stderr)
            print(f"Exception type: {type(e).__name__}", file=sys.stderr)
            print(f"Exception message: {e}", file=sys.stderr)
            print("\nFull traceback:", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            print("=" * 80, file=sys.stderr)
            print("=" * 80, file=sys.stderr)
            # Re-raise to show actual error in Django Admin
            raise

    def changelist_view(self, request, extra_context=None):
        """The 'change list' admin view for this model.

        Override to catch errors during changelist rendering.
        """
        try:
            return super().changelist_view(request, extra_context)
        except Exception as e:
            # Log the full error with traceback
            logger.error(
                f"Error in {self.__class__.__name__}.changelist_view for {self.model.__name__}: {e}",
                exc_info=True,
                stack_info=True
            )
            # Print to stderr for immediate visibility (always shows)
            import sys
            print("=" * 80, file=sys.stderr)
            print("=" * 80, file=sys.stderr)
            print(f"ERROR in {self.__class__.__name__}.changelist_view for {self.model.__name__}:", file=sys.stderr)
            print(f"Exception type: {type(e).__name__}", file=sys.stderr)
            print(f"Exception message: {e}", file=sys.stderr)
            print("\nFull traceback:", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            print("=" * 80, file=sys.stderr)
            print("=" * 80, file=sys.stderr)

            # Capture full traceback as string
            traceback_buffer = StringIO()
            traceback.print_exc(file=traceback_buffer)
            traceback_str = traceback_buffer.getvalue()

            # Return HttpResponse with full error details instead of re-raising
            # This bypasses Django's generic error handling
            error_html = format_html(
                """
                <html>
                <head><title>Django Admin Error - {}</title></head>
                <body>
                    <h1>Error in {} for {}</h1>
                    <h2>Exception Type: {}</h2>
                    <h2>Exception Message:</h2>
                    <pre style="background: #f0f0f0; padding: 10px; border: 1px solid #ccc;">{}</pre>
                    <h2>Full Traceback:</h2>
                    <pre style="background: #f0f0f0; padding: 10px; border: 1px solid #ccc; white-space: pre-wrap;">{}</pre>
                </body>
                </html>
                """,
                self.model.__name__,
                self.__class__.__name__,
                self.model.__name__,
                type(e).__name__,
                str(e),
                traceback_str
            )
            return HttpResponse(error_html, status=500)
