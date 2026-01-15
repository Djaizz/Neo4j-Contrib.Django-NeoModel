"""Django Admin integration for NeoModel nodes."""


import logging
import traceback
from typing import Any

from django.contrib.admin import ModelAdmin
from django.http import HttpRequest
from django.utils.html import format_html

from neomodel.match_q import Q, QBase
from neomodel.sync_.match import NodeSet

from . import DjangoNode


__all__ = ['DjangoNeoModelAdmin']


# ============================================================================
# Monkey-patch for Q Filters Parsing Issue
# ============================================================================
#
# PROBLEM:
# NeoModel's `_parse_q_filters` method (in `neomodel/sync_/match.py`) has a bug where
# `isinstance(child, QBase)` returns False for Q objects that are nested as children
# in q_filters. This happens when filter() is called, which does:
#
#     self.q_filters = Q(self.q_filters & Q(...))
#
# This wraps the combined Q in another Q(), creating: Q(Q(...)) structure. When the
# parser processes this, it checks `isinstance(child, QBase)` for each child. For some
# reason (possibly import/class hierarchy issues), this check returns False for Q objects,
# causing the parser to try to subscript the Q object as a tuple (child[0], child[1]),
# leading to "'Q' object is not subscriptable" errors.
#
# ROOT CAUSE:
# The issue occurs when q_filters has Q objects as direct children (from filter() wrapping
# or from combining Q objects using the & operator). The original parser's isinstance()
# check fails to recognize these Q objects as QBase instances, even though Q inherits
# from QBase.
#
# SOLUTION:
# We monkey-patch `QueryBuilder._parse_q_filters` to use enhanced Q object detection:
# 1. Multiple detection methods: isinstance(child, QBase), isinstance(child, Q), and
#    type name check as fallback
# 2. Error handling: If subscripting fails, check if child looks like a Q object and
#    handle it accordingly
# 3. Recursive calls use the patched version (self._parse_q_filters) to ensure all
#    nested levels are handled correctly
#
# This ensures that Q objects in children are always recognized and processed correctly,
# regardless of whether isinstance() works properly.
#
# ============================================================================

_original_parse_q_filters = None


def _patched_parse_q_filters(self, ident: str, q: QBase | Any, source_class):
    """Patched version of _parse_q_filters that handles Q objects in children.

    This patch fixes the issue where isinstance(child, QBase) returns False for Q objects
    that are nested as children in q_filters, causing "'Q' object is not subscriptable" errors.

    The patch uses multiple detection methods to identify Q objects and handles them correctly,
    even when isinstance() fails.
    """
    from neomodel.match_q import Q as QClass
    target: list[tuple[str, bool]] = []

    def add_to_target(statement: str, connector, optional: bool) -> None:
        if not statement:
            return
        if connector == QClass.OR:
            statement = f"({statement})"
        target.append((statement, optional))

    for child in q.children:
        # Enhanced Q object detection using multiple methods:
        # 1. isinstance(child, QBase) - Standard check (may fail due to import/class issues)
        # 2. isinstance(child, Q) - Direct Q class check
        # 3. type(child).__name__ == 'Q' - Fallback type name check
        # This ensures we catch Q objects even when isinstance() fails
        is_qbase = isinstance(child, QBase) or isinstance(child, QClass) or type(child).__name__ == 'Q'

        if is_qbase:
            # Use self._parse_q_filters (our patched version) for recursive calls
            # This ensures all nested Q objects are handled correctly at all levels
            q_childs, q_opt_childs = self._parse_q_filters(
                ident, child, source_class
            )
            add_to_target(q_childs, child.connector, False)
            add_to_target(q_opt_childs, child.connector, True)
        else:
            # Must be a tuple from kwargs.items() (normal case)
            try:
                kwargs = {child[0]: child[1]}
                from neomodel.sync_.match import process_filter_args
                filters = process_filter_args(source_class, kwargs)
                self._build_filter_statements(ident, filters, target, source_class)
            except (TypeError, IndexError) as e:
                # If child is not subscriptable, it's likely a Q object that wasn't recognized
                # by our enhanced check. This can happen in edge cases.
                # Check if it has Q-like attributes and handle it as a Q object
                logger.warning(
                    f"Child in q_filters.children is not subscriptable: {type(child).__name__}. "
                    f"Attempting to handle as QBase. Error: {e}"
                )
                if hasattr(child, 'children') and hasattr(child, 'connector'):
                    # Looks like a Q object (has children and connector attributes)
                    # Process it using our patched version
                    q_childs, q_opt_childs = self._parse_q_filters(
                        ident, child, source_class
                    )
                    add_to_target(q_childs, child.connector, False)
                    add_to_target(q_opt_childs, child.connector, True)
                else:
                    # Not a Q object and not subscriptable - this is unexpected
                    raise

    # Build match and optional match filter statements
    match_filters = [filter[0] for filter in target if not filter[1]]
    opt_match_filters = [filter[0] for filter in target if filter[1]]

    # Handle OR connector with both match and optional match filters
    if q.connector == QClass.OR and match_filters and opt_match_filters:
        # Can't split filters, so move everything to optional match filters
        opt_match_filters += match_filters
        match_filters = []
        self._ast.mixed_filters = True

    # Build final WHERE clause strings
    ret = f" {q.connector} ".join(match_filters)
    if ret and q.negated:
        ret = f"NOT ({ret})"
    opt_ret = f" {q.connector} ".join(opt_match_filters)
    if opt_ret and q.negated:
        opt_ret = f"NOT ({opt_ret})"
    return ret, opt_ret


def _apply_q_filters_patch():
    """Apply monkey-patch to _parse_q_filters to handle Q objects in children.

    This patch is applied on module import to ensure it's active before any
    QueryBuilder instances are created.
    """
    global _original_parse_q_filters
    from neomodel.sync_.match import QueryBuilder
    if _original_parse_q_filters is None:
        _original_parse_q_filters = QueryBuilder._parse_q_filters
        QueryBuilder._parse_q_filters = _patched_parse_q_filters


# Apply patch on module import to ensure it's active before any QueryBuilder instances are created
_apply_q_filters_patch()


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

    # BaseModelAdmin options
    # ======================
    # autocomplete_fields = ()
    # raw_id_fields = ()
    # fields = None
    # exclude = None
    # fieldsets = None
    # form = forms.ModelForm
    # filter_vertical = ()
    # filter_horizontal = ()
    # radio_fields = {}
    # prepopulated_fields = {}
    # formfield_overrides = {}
    # readonly_fields = ()
    # ordering = None
    # sortable_by = None
    # view_on_site = True
    # show_full_result_count = True
    # checks_class = BaseModelAdminChecks

    # ModelAdmin options
    # ==================
    # list_display = ("__str__",)
    # list_display_links = ()
    # list_filter = ()
    # list_select_related = False
    # list_per_page = 100
    # list_max_show_all = 200
    # list_editable = ()
    # search_fields = ()
    # search_help_text = None
    # date_hierarchy = None
    # save_as = False
    # save_as_continue = True
    # save_on_top = False
    # paginator = Paginator
    # preserve_filters = True
    # show_facets = ShowFacets.ALLOW
    # inlines = ()

    # Custom templates (designed to be over-ridden in subclasses)
    # -----------------------------------------------------------
    # add_form_template = None
    # change_form_template = None
    # change_list_template = None
    # delete_confirmation_template = None
    # delete_selected_confirmation_template = None
    # object_history_template = None
    # popup_response_template = None

    # Actions
    # -------
    # actions = ()
    # action_form = helpers.ActionForm
    # actions_on_top = True
    # actions_on_bottom = False
    # actions_selection_counter = True
    # checks_class = ModelAdminChecks

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Return True if the given request has permission to add a new object."""
        return True

    def has_view_permission(self,
                            request: HttpRequest,
                            obj: DjangoNode | None = None) -> bool:
        """Return True if the given request has permission to view the given model instance.

        This is required for Django Admin's changelist_view, which checks
        has_view_or_change_permission, which in turn calls has_view_permission.
        """
        return True

    def has_change_permission(self,
                              request: HttpRequest,
                              obj: DjangoNode | None = None) -> bool:
        """Return True if the given request has permission to change the given model instance."""
        return True

    def has_view_or_change_permission(self,
                                      request: HttpRequest,
                                      obj: DjangoNode | None = None) -> bool:
        """Return True if the request has permission to view or change the model instance.

        This is checked by changelist_view before displaying the changelist.
        """
        return self.has_view_permission(request, obj) or self.has_change_permission(request, obj)

    def has_delete_permission(self,
                              request: HttpRequest,
                              obj: DjangoNode | None = None) -> bool:
        """Return True if the given request has permission to delete the given model instance."""
        return True

    def get_ordering(self, request):
        """Return the ordering for the changelist, translating 'pk' to actual primary key field.

        Django Admin may try to order by 'pk', but NeoModel doesn't recognize 'pk' as a property.
        This method translates 'pk' to the actual primary key field name (e.g., 'label').
        """
        ordering = super().get_ordering(request)

        # Get the actual primary key field name from model._meta.pk.name
        # (set by DjangoNode._meta when creating the pk property)
        pk_field_name = getattr(self.model._meta.pk, 'name', None)

        if not pk_field_name:
            # If we can't find the primary key field, return empty ordering to avoid errors
            return []

        # If no ordering specified, default to ordering by primary key
        if not ordering:
            ordering = ['pk']

        # Translate 'pk' to actual primary key field name
        translated_ordering = []
        for field in ordering:
            if field == 'pk' or field == '-pk':
                # Translate to actual field name, preserving the '-' prefix
                translated_field = f"-{pk_field_name}" if field.startswith('-') else pk_field_name
                translated_ordering.append(translated_field)
            else:
                translated_ordering.append(field)

        return translated_ordering

    def get_search_results(self, request, queryset, search_term):
        """Override to handle search using neomodel filters instead of Django Q objects.

        This default implementation handles search across all fields in `search_fields` using
        NeoModel's Q objects with OR logic. Subclasses can override for custom search behavior.
        """
        if search_term and self.search_fields and len(self.search_fields) > 0:
            # Build a single Q object with OR conditions for all search fields
            # Instead of combining multiple Q objects (which can cause structure issues),
            # build a single Q object with all conditions as kwargs
            # This creates children as tuples (from kwargs.items()), not nested Q objects
            search_kwargs = {}
            for field in self.search_fields:
                search_kwargs[f"{field}__icontains"] = search_term

            # Create a single Q object with OR connector and all conditions
            # This ensures children are tuples, not nested Q objects
            search_q = Q(_connector=Q.OR, **search_kwargs)

            # Directly manipulate q_filters instead of using filter() to avoid structure issues
            # filter() does: self.q_filters = Q(self.q_filters & Q(...)) which wraps the combined Q
            # in another Q(), creating: Q(Q(existing) & Q(new)). While the monkey-patch handles this
            # correctly, it's still better to avoid the extra wrapping by using the & operator directly.
            #
            # Note: The monkey-patch (applied on module import) ensures Q objects in children are
            # always recognized and processed correctly, so we can safely combine q_filters.
            if not hasattr(queryset, 'q_filters'):
                # No q_filters attribute (shouldn't happen for NodeSet)
                logger.error(
                    f"NodeSet for {self.model.__name__} has no q_filters attribute. "
                    f"Cannot apply search."
                )
                return queryset, False

            # Get existing q_filters and combine with search_q using & operator
            # The monkey-patch handles Q objects in children correctly, so we can safely combine
            existing_q = queryset.q_filters

            # Check if q_filters is truly empty (no children)
            # Empty Q() evaluates to False and has len() == 0
            if not existing_q or len(existing_q) == 0:
                # Empty q_filters, just set our search_q directly
                queryset.q_filters = search_q
            else:
                # Existing q_filters - combine using & operator directly
                # This creates: Q(AND, [existing_q, search_q])
                # The monkey-patch ensures Q objects in children are handled correctly
                queryset.q_filters = existing_q & search_q
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
                f"Error in {self.__class__.__name__}.get_changelist for "
                f"{self.model.__name__}: {e}",
                exc_info=True,
                stack_info=True
            )
            # Print to stderr for immediate visibility (always shows)
            import sys
            print("=" * 80, file=sys.stderr)
            print("=" * 80, file=sys.stderr)
            print(
                f"ERROR in {self.__class__.__name__}.get_changelist for "
                f"{self.model.__name__}:",
                file=sys.stderr
            )
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
                f"Error in {self.__class__.__name__}.changelist_view for "
                f"{self.model.__name__}: {e}",
                exc_info=True,
                stack_info=True
            )
            # Print to stderr for immediate visibility (always shows)
            import sys
            print("=" * 80, file=sys.stderr)
            print("=" * 80, file=sys.stderr)
            print(
                f"ERROR in {self.__class__.__name__}.changelist_view for "
                f"{self.model.__name__}:",
                file=sys.stderr
            )
            print(f"Exception type: {type(e).__name__}", file=sys.stderr)
            print(f"Exception message: {e}", file=sys.stderr)
            print("\nFull traceback:", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            print("=" * 80, file=sys.stderr)
            print("=" * 80, file=sys.stderr)

            # Return HTML error page if DEBUG is True
            from django.conf import settings
            if settings.DEBUG:
                from django.http import HttpResponse
                error_html = format_html(
                    "<h1>Error in changelist_view</h1>"
                    "<p><strong>Exception type:</strong> {}</p>"
                    "<p><strong>Exception message:</strong> {}</p>"
                    "<pre>{}</pre>",
                    type(e).__name__,
                    str(e),
                    traceback.format_exc()
                )
                return HttpResponse(error_html, status=500)
            # Re-raise if not DEBUG
            raise

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        """The 'change' admin view for this model.

        Override to catch errors during change form rendering and ensure
        extra_context is properly initialized.
        """
        # Ensure extra_context is a dict, not None
        if extra_context is None:
            extra_context = {}

        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except Exception as e:
            # Log the full error with traceback
            logger.error(
                f"Error in {self.__class__.__name__}.changeform_view for "
                f"{self.model.__name__}: {e}",
                exc_info=True,
                stack_info=True
            )
            # Print to stderr for immediate visibility (always shows)
            import sys
            print("=" * 80, file=sys.stderr)
            print("=" * 80, file=sys.stderr)
            print(
                f"ERROR in {self.__class__.__name__}.changeform_view for "
                f"{self.model.__name__}:",
                file=sys.stderr
            )
            print(f"Exception type: {type(e).__name__}", file=sys.stderr)
            print(f"Exception message: {e}", file=sys.stderr)
            print("\nFull traceback:", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            print("=" * 80, file=sys.stderr)
            print("=" * 80, file=sys.stderr)
            # Re-raise to show actual error in Django Admin
            raise

    def get_readonly_fields(self, request, obj=None):
        """Return readonly fields, excluding NeoModel internal fields.

        This prevents Django Admin from displaying NeoModel internal fields
        like 'element_id_property' in the form.
        """
        readonly = list(super().get_readonly_fields(request, obj) or [])
        # Exclude NeoModel internal fields from being displayed
        internal_fields = ['element_id', 'element_id_property']
        readonly = [f for f in readonly if f not in internal_fields]
        return readonly

    def get_form(self, request, obj=None, **kwargs):
        """Return a ModelForm class for use in the admin.

        Override to ensure the form is properly configured for NeoModel nodes
        and excludes internal fields.
        """
        # Exclude NeoModel internal fields from the form
        if 'exclude' not in kwargs:
            kwargs['exclude'] = []
        if not isinstance(kwargs['exclude'], list):
            kwargs['exclude'] = list(kwargs['exclude'])
        # Add NeoModel internal fields to exclude list
        internal_fields = ['element_id', 'element_id_property']
        for field in internal_fields:
            if field not in kwargs['exclude']:
                kwargs['exclude'].append(field)

        form = super().get_form(request, obj, **kwargs)
        return form

    def get_queryset(self, request):
        """Return a queryset for use in Django Admin with translated ordering.

        This ensures we return a properly initialized NodeSet from the model's objects manager,
        and applies the translated ordering (pk -> actual field name) to the queryset.

        Also ensures q_filters is in a valid state to prevent parsing errors.
        """
        try:
            # self.model.objects returns cls.nodes (a NodeSet), not the result of .all()
            # We use the NodeSet directly, not .all() which returns a list
            queryset = self.model.objects

            # Ensure we have a NodeSet
            if not isinstance(queryset, NodeSet):
                # This should never happen if _ObjectsDescriptor is working correctly
                raise TypeError(
                    f"Expected NodeSet but got {type(queryset).__name__} for {self.model.__name__}. "
                    f"self.model.objects type: {type(self.model.objects).__name__}"
                )

            # Wrap the NodeSet's order_by method to automatically translate 'pk'
            # This ensures that even if Django Admin applies ordering later, 'pk' will be translated
            # We also need to handle clones, so we store the wrapper info on the instance
            pk_field_name = getattr(self.model._meta.pk, 'name', None)
            if pk_field_name:
                # Store the original order_by and pk_field_name on the instance
                # so clones can also use the wrapper
                if not hasattr(queryset, '_original_order_by'):
                    queryset._original_order_by = queryset.order_by
                    queryset._pk_field_name = pk_field_name

                # Create a closure that captures pk_field_name
                def make_translated_order_by(node_set, original_order_by, pk_field):
                    """Create a wrapper function that translates 'pk' to actual field name."""
                    def translated_order_by(*props):
                        """Wrapper that translates 'pk' to actual field name before calling order_by."""
                        translated_props = []
                        for prop in props:
                            if isinstance(prop, str):
                                if prop == 'pk':
                                    translated_props.append(pk_field)
                                elif prop == '-pk':
                                    translated_props.append(f"-{pk_field}")
                                elif prop.startswith('-') and prop[1:] == 'pk':
                                    translated_props.append(f"-{pk_field}")
                                elif 'pk' in prop:
                                    # Handle cases like "pk DESC" or similar
                                    translated_props.append(prop.replace('pk', pk_field))
                                else:
                                    translated_props.append(prop)
                            else:
                                translated_props.append(prop)
                        result = original_order_by(*translated_props)
                        # Ensure the wrapper is also applied to the result (in case order_by returns a new NodeSet)
                        if isinstance(result, NodeSet) and not hasattr(result, '_original_order_by'):
                            result._original_order_by = original_order_by
                            result._pk_field_name = pk_field
                            result.order_by = make_translated_order_by(result, original_order_by, pk_field)
                        return result
                    return translated_order_by

                queryset.order_by = make_translated_order_by(queryset, queryset._original_order_by, pk_field_name)

            # Get the translated ordering from get_ordering()
            # This will have already translated 'pk' to the actual field name
            ordering = self.get_ordering(request)

            # Debug: Log the ordering to verify translation
            if ordering and any('pk' in str(field) for field in ordering):
                logger.warning(
                    f"get_ordering() returned ordering with 'pk' for {self.model.__name__}: {ordering}. "
                    f"This should have been translated!"
                )

            # Clear any existing ordering first (in case Query.order_by default is set)
            # NodeSet.order_by() with no args clears ordering, but we'll apply our own
            if hasattr(queryset, 'order_by_elements'):
                queryset.order_by_elements = []

            # Also clear/update the Query.order_by if it exists
            if hasattr(queryset, 'query') and hasattr(queryset.query, 'order_by'):
                queryset.query.order_by = ordering if ordering else []

            # Apply the translated ordering to the queryset
            # NodeSet.order_by() accepts field names as strings
            if ordering:
                # Ensure no 'pk' in ordering before applying
                if any('pk' in str(field) for field in ordering):
                    raise ValueError(
                        f"Ordering contains 'pk' after translation for {self.model.__name__}: {ordering}. "
                        f"This should have been translated to the actual primary key field name."
                    )
                queryset = queryset.order_by(*ordering)

            # Ensure q_filters is in a valid state (not None)
            # Note: The monkey-patch (applied on module import) handles Q objects in children
            # correctly, so we only need to ensure q_filters is not None here.
            if hasattr(queryset, 'q_filters'):
                from neomodel.match_q import Q
                if queryset.q_filters is None:
                    queryset.q_filters = Q()

            # Verify the ordering was applied correctly
            if hasattr(queryset, 'order_by_elements'):
                # Check if 'pk' is still in order_by_elements (shouldn't be)
                for elem in queryset.order_by_elements:
                    if isinstance(elem, str) and (elem == 'pk' or elem == '-pk' or elem.endswith('.pk')):
                        raise ValueError(
                            f"'pk' found in order_by_elements after translation for {self.model.__name__}. "
                                f"Translated ordering: {ordering}, order_by_elements: {queryset.order_by_elements}"
                            )

            # IMPORTANT: Ensure order_by_elements doesn't contain 'pk' before returning
            # Django Admin's ChangeList might clone the queryset, so we need to ensure
            # the ordering is correct at this point
            if hasattr(queryset, 'order_by_elements'):
                # Double-check that no 'pk' slipped through and fix it
                pk_field_name = getattr(self.model._meta.pk, 'name', None)
                if pk_field_name:
                    # Create a new list with translated elements
                    translated_elements = []
                    for elem in queryset.order_by_elements:
                        if isinstance(elem, str):
                            if elem == 'pk':
                                translated_elements.append(pk_field_name)
                            elif elem == '-pk':
                                translated_elements.append(f"-{pk_field_name}")
                            elif elem.endswith('.pk'):
                                translated_elements.append(elem.replace('.pk', f'.{pk_field_name}'))
                            elif 'pk' in elem:
                                # Handle cases like "pk DESC" or similar
                                translated_elements.append(elem.replace('pk', pk_field_name))
                            else:
                                translated_elements.append(elem)
                        else:
                            translated_elements.append(elem)
                    queryset.order_by_elements = translated_elements
                else:
                    # Can't translate, remove any 'pk' elements
                    queryset.order_by_elements = [
                        elem for elem in queryset.order_by_elements
                        if not (isinstance(elem, str) and ('pk' in elem))
                    ]
                    if queryset.order_by_elements != list(queryset.order_by_elements):
                        logger.warning(
                            f"Removed 'pk' from order_by_elements for {self.model.__name__} "
                            f"because primary key field name could not be determined"
                        )

            return queryset
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


class _DjangoNeoModelAdmin:
    """Private class for methods that need validation.

    Methods moved here are proactive overrides that may be unnecessary
    if underlying incompatibilities are fixed at the NodeSet/DjangoNode level.
    """

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
                raise ValueError(
                    f"{self.model.__name__} must have a field with primary_key=True"
                )

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
                raise Http404(
                    f"{self.model._meta.verbose_name} with pk={object_id} does not exist."
                )
            # For other exceptions, log and re-raise
            logger.error(
                f"Exception in {self.__class__.__name__}.get_object for "
                f"{self.model.__name__}: {e}",
                exc_info=True,
                stack_info=True
            )
            raise
