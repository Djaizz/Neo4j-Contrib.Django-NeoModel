# Django-NeoModel Key Affordances and Interfaces Survey

This document enumerates all key affordances and interfaces implemented in Django-NeoModel, along with justifications for their necessity.

---

## Module: `__init__.py`

### 1. **`DjangoField` class** (lines 38-161)
- **Purpose**: Wraps NeoModel `Property` objects to mimic Django `Field` API
- **Justification**: Django Admin and forms expect Django `Field` objects with attributes like `name`, `verbose_name`, `formfield()`, `has_default()`, etc. NeoModel `Property` objects don't have this interface.
- **Key attributes**:
  - `empty_values = [None, '']` - Django's `display_for_field()` expects `field.empty_values`
- **Key methods**:
  - `formfield()` - Converts to Django form field
  - `save_form_data()` - Saves form data to instance
  - `value_from_object()` - Extracts value from instance
  - `get_choices()` - Handles choice fields
- **Necessity**: ✅ **Required** for Django Admin/forms integration

### 2. **`Query` dataclass** (lines 164-168)
- **Purpose**: Mimics Django QuerySet's `query` attribute for Django Admin compatibility
- **Justification**: Django Admin expects querysets to have a `query` attribute with `order_by`. NeoModel `NodeSet` doesn't have this.
- **Necessity**: ⚠️ **Potentially removable** - May not be used if Django Admin doesn't actually need it

### 3. **`_ObjectsDescriptor` class** (lines 171-184)
- **Purpose**: Provides Django-like `.objects` API (`Model.objects.all()` instead of `Model.nodes.all()`)
- **Justification**: Django Admin and Django code expect `.objects` manager. NeoModel uses `.nodes`.
- **Necessity**: ✅ **Required** for Django Admin compatibility and Django-like API

### 4. **`NeoManager` class** (lines 186-198)
- **Purpose**: Django-style manager wrapper for NeoModel nodes that provides `get_queryset()` method
- **Justification**: Django Admin expects models to have `_default_manager` attribute pointing to a manager-like object with `get_queryset()`. This wrapper provides that interface.
- **Key methods**:
  - `__init__(model)` - Initializes manager with the model class
  - `get_queryset()` - Returns a `NodeSet` for the model
- **Necessity**: ✅ **Required** for Django Admin compatibility (Django Admin accesses `_default_manager`)

### 5. **`MetaClass` class** (lines 201-213)
- **Purpose**: Metaclass that extends NeoModel's `NodeMeta` to automatically set `_default_manager` on DjangoNode subclasses
- **Justification**: Django Admin expects models to have `_default_manager` attribute. This metaclass ensures it's set during class creation, before Django Admin tries to access it.
- **Implementation**: Extends `NodeMeta` and sets `_default_manager = NeoManager(new_cls)` in `__new__()`
- **Necessity**: ✅ **Required** for Django Admin compatibility (sets `_default_manager` at class creation time)

### 6. **`DjangoNode` class** (lines 216-344)
- **Purpose**: Base class for NeoModel nodes with Django integration
- **Justification**: Bridges NeoModel and Django expectations

**Key methods/attributes:**

#### **`objects` attribute** (line 192)
- **Purpose**: Django-like manager accessor
- **Justification**: Django Admin expects `Model.objects.all()`
- **Necessity**: ✅ **Required**

#### **`_meta` classproperty** (lines 194-234)
- **Purpose**: Creates Django `Options` object with field metadata
- **Justification**: Django Admin uses `Model._meta` for introspection (fields, verbose_name, etc.)
- **Key features**:
  - Converts NeoModel properties to `DjangoField` objects
  - Creates `pk` property that returns actual primary key value (not Property object)
  - Uses `PkProperty` to support Django Admin's expectation of `pk.name`
- **Necessity**: ✅ **Required** for Django Admin

#### **`full_clean()` method** (lines 236-254)
- **Purpose**: Validates node and raises Django `ValidationError`
- **Justification**: Django forms call `full_clean()` before saving
- **Necessity**: ✅ **Required** for Django forms integration

#### **`validate_unique()` method** (lines 256-277)
- **Purpose**: Validates unique constraints
- **Justification**: Django forms call this during validation
- **Necessity**: ✅ **Required** for Django forms integration

#### **`validate_constraints()` method** (lines 303-313)
- **Purpose**: No-op method for Django Admin compatibility
- **Justification**: Django Admin's `ModelForm` calls `validate_constraints()` on model instances
- **Necessity**: ✅ **Required** (no-op is fine since NeoModel doesn't have Django ORM constraints)

#### **Django Signals Integration** (lines 279-298)
- **Methods**: `pre_save()`, `post_save()`, `pre_delete()`, `post_delete()`
- **Purpose**: Emits Django signals for lifecycle events
- **Justification**: Django apps expect signals for model lifecycle events
- **Necessity**: ✅ **Required** if Django apps depend on signals

#### **`serializable_value()` method** (lines 300-301)
- **Purpose**: Returns serializable value for a field
- **Justification**: Django Admin calls this for serialization
- **Necessity**: ✅ **Required** for Django Admin

### 7. **`classproperty` decorator** (lines 26-34)
- **Purpose**: Creates class-level properties (like `_meta`)
- **Justification**: `_meta` needs to be a class property, not an instance property
- **Necessity**: ✅ **Required** for `_meta` implementation

### 8. **`DjangoNode.serializable_value()` method** (in `DjangoNode` class, lines 336-342)
- **Purpose**: Handles `None` field names (Django Admin sometimes passes `None`)
- **Justification**: Django Admin sometimes calls `serializable_value(None)`, which causes `TypeError`
- **Necessity**: ✅ **Required** to prevent crashes in Django Admin
- **Implementation**: Implemented directly in `DjangoNode.serializable_value()` method to handle edge cases

---

## Module: `admin.py`

### 1. **`DjangoNeoModelAdmin` class** (lines 22-236)
- **Purpose**: Base `ModelAdmin` for NeoModel nodes
- **Justification**: Django Admin needs customizations to work with NeoModel
- **Note**: Unlike `DjangoNode` integrations (which are **reactive** - Django calls/accesses them), these are **proactive** overrides of Django Admin's defaults. Their necessity depends on whether the underlying incompatibilities could be fixed at a lower level (e.g., making NodeSet compatible with Django Admin's expectations).

**Key methods:**

#### **Permission methods** (lines 35-65)
- `has_add_permission()`, `has_change_permission()`, `has_delete_permission()`, `has_view_permission()`, `has_view_or_change_permission()`
- **Purpose**: Bypass Django's permission system (all return `True`)
- **Justification**: NeoModel doesn't integrate with Django's auth system
- **Necessity**: ✅ **Required** for Django Admin to display pages
- **Validation needed**: ⚠️ Could Django Admin work without these if we integrated with Django's auth system?

#### **`get_ordering()` method** (lines 71-101)
- **Purpose**: Translates `pk` to actual primary key field name (e.g., `label`) for NeoModel compatibility
- **Justification**: Django Admin uses `pk` for ordering, but NeoModel doesn't recognize `pk` as a property. NeoModel requires the actual property name (e.g., `label`).
- **Implementation**:
  - Gets primary key field name from `model._meta.pk.name`
  - Translates `'pk'` and `'-pk'` to actual field names
  - Returns translated ordering list
- **Necessity**: ✅ **Required** - NeoModel's query builder validates property names and will raise `ValueError` if `pk` is used

#### **`get_queryset()` method** (lines 103-200)
- **Purpose**: Returns NodeSet with translated ordering and intercepts `order_by()` calls to translate `pk`
- **Justification**:
  - Django Admin expects a queryset; `model.objects` returns a NodeSet (not `model.objects.all()` which returns a list)
  - Must apply translated ordering from `get_ordering()`
  - Must wrap `order_by()` to intercept any `pk` usage (Django Admin may apply ordering after `get_queryset()` returns)
- **Key features**:
  - Uses `model.objects` directly (NodeSet), not `model.objects.all()` (list)
  - Applies translated ordering from `get_ordering()`
  - Wraps NodeSet's `order_by()` method to automatically translate `pk` to actual field name
  - Ensures wrapper is applied to cloned NodeSets (when `order_by()` returns a new NodeSet)
  - Safety check: Cleans `order_by_elements` to remove any `pk` that slipped through
- **Necessity**: ✅ **Required** -
  - Must use NodeSet directly (not `.all()` which returns a list)
  - Must translate `pk` before NeoModel's query builder validates properties
  - Must intercept `order_by()` because Django Admin may apply ordering after `get_queryset()` returns

#### **`get_object()` method** (lines 96-127)
- **Purpose**: Retrieves single object by primary key
- **Justification**: Django Admin's default expects Django ORM queryset `.get()`. NeoModel uses custom primary keys (not `id`).
- **Necessity**: ⚠️ **Needs validation** - Could Django Admin's default work if NodeSet's `.get()` method properly handled custom primary keys?
- **Current implementation**: Custom logic to find pk field and query by it

#### **`get_search_results()` method** (lines 484-520)
- **Purpose**: Implements search using NeoModel's `Q` objects
- **Justification**: Django Admin's default uses Django ORM `Q` objects. NeoModel has its own `Q` objects.
- **Implementation**:
  - Builds a single Q object with OR conditions for all search fields
  - Directly manipulates `q_filters` using `&` operator (avoids `filter()` which wraps in Q())
  - The monkey-patch ensures Q objects in children are handled correctly
- **Necessity**: ✅ **Required** - Django Admin's default uses Django ORM `Q` objects, which are incompatible with NeoModel's `Q` objects. NeoModel requires its own `Q` objects for filtering.

#### **`get_changelist()` method** (lines 154-180)
- **Purpose**: Error handling wrapper for ChangeList creation
- **Justification**: Better error visibility during debugging
- **Necessity**: ⚠️ **Debugging helper**, not strictly required

#### **`changelist_view()` method** (lines 182-236)
- **Purpose**: Error handling wrapper that returns HTML error page
- **Justification**: Better error visibility during debugging
- **Necessity**: ⚠️ **Debugging helper**, not strictly required

---

## Module: `apps.py`

### 1. **`NeomodelConfig` class** (lines 6-22)
- **Purpose**: Django AppConfig that reads NeoModel settings from Django settings
- **Justification**: Integrates NeoModel configuration with Django's settings system
- **Key features**:
  - Reads `NEOMODEL_NEO4J_BOLT_URL` from Django settings
  - Reads `NEOMODEL_FORCE_TIMEZONE` from Django settings
  - Reads `NEOMODEL_MAX_CONNECTION_POOL_SIZE` from Django settings
- **Necessity**: ✅ **Required** for NeoModel to work within Django

---

## Module: `management/commands/`

### 1. **`install_labels` command** (lines 7-11)
- **Purpose**: Django management command wrapper for `neomodel.install_all_labels()`
- **Justification**: Provides Django-style command interface for NeoModel operations
- **Necessity**: ⚠️ **Convenience feature**, not strictly required

### 2. **`clear_neo4j` command** (lines 6-11)
- **Purpose**: Django management command wrapper for `neomodel.clear_neo4j_database()`
- **Justification**: Provides Django-style command interface for NeoModel operations
- **Necessity**: ⚠️ **Convenience feature**, not strictly required

---

## Summary

### **Core Requirements (Fully Justified - Reactive to Django's API):**
1. ✅ `DjangoField` - Required for Django Admin/forms (Django accesses field attributes)
2. ✅ `DjangoNode` with `_meta`, `full_clean()`, `validate_unique()`, `validate_constraints()`, `serializable_value()` - Required (Django calls these methods)
3. ✅ `_ObjectsDescriptor` / `.objects` - Required (Django Admin expects `Model.objects.all()`)
4. ✅ `NeoManager` - Required (Django Admin expects `_default_manager` with `get_queryset()` method)
5. ✅ `MetaClass` - Required (sets `_default_manager` during class creation for Django Admin compatibility)
6. ✅ Django Signals Integration - Required (if Django apps depend on signals)
7. ✅ `DjangoField.empty_values` class attribute - Required (Django's `display_for_field()` accesses this)
8. ✅ `NeomodelConfig` - Required for NeoModel configuration in Django
9. ✅ `DjangoNeoModelAdmin.get_ordering()` - Required (translates `pk` to actual field name for NeoModel compatibility)
10. ✅ `DjangoNeoModelAdmin.get_queryset()` - Required (uses NodeSet directly, applies translated ordering, intercepts `order_by()` to translate `pk`)
11. ✅ `DjangoNeoModelAdmin.get_search_results()` - Required (converts Django Admin search to NeoModel Q objects)
12. ✅ **Q Filters Parsing Monkey-Patch** (in `admin.py`, lines 16-78) - Required (fixes NeoModel bug where `isinstance(child, QBase)` fails for nested Q objects)
11. ✅ `DjangoNeoModelAdmin.get_search_results()` - Required (converts Django Admin search to NeoModel Q objects)
12. ✅ **Q Filters Parsing Monkey-Patch** - Required (fixes NeoModel bug where `isinstance(child, QBase)` fails for nested Q objects)

### **Needs Validation (Proactive Overrides - May Be Unnecessary):**
1. ⚠️ `DjangoNeoModelAdmin` permission methods - Could Django Admin work without these if we integrated with Django's auth system?
2. ⚠️ `DjangoNeoModelAdmin.get_object()` - Could Django Admin's default work if NodeSet's `.get()` method properly handled custom primary keys?

### **Potentially Removable (Debugging/Convenience):**
1. ⚠️ `Query` dataclass - May not be used if Django Admin doesn't need it
2. ⚠️ `DjangoNeoModelAdmin.get_changelist()` - Debugging helper
3. ⚠️ `DjangoNeoModelAdmin.changelist_view()` - Debugging helper
4. ⚠️ Management commands - Convenience features

### **Key Intercepts and Overrides:**

#### **Primary Key (`pk`) Translation Intercept**
- **Problem**: Django Admin uses `pk` for ordering, but NeoModel doesn't recognize `pk` as a property. NeoModel requires the actual property name (e.g., `label`).
- **Solution**: Multi-layered intercept strategy:
  1. **`get_ordering()` override**: Translates `pk` → actual field name when Django Admin requests ordering
  2. **`get_queryset()` override**:
     - Applies translated ordering from `get_ordering()`
     - Wraps NodeSet's `order_by()` method to intercept any `pk` usage
     - Ensures wrapper propagates to cloned NodeSets
  3. **Safety check**: Cleans `order_by_elements` before returning queryset to catch any `pk` that slipped through
- **Why necessary**: NeoModel's query builder validates property names at query build time (line 545 in `neomodel/sync_/match.py`), raising `ValueError` if `pk` is used. Django Admin may apply ordering after `get_queryset()` returns, so we must intercept at the `order_by()` level.

#### **NodeSet vs List Distinction**
- **Problem**: `model.objects.all()` returns a `list`, not a `NodeSet`. Django Admin expects a queryset-like object.
- **Solution**: Use `model.objects` directly (which is a NodeSet via `_ObjectsDescriptor`), not `model.objects.all()`.
- **Why necessary**: Django Admin's ChangeList and paginator expect a queryset-like object with methods like `count()`, `order_by()`, etc. A `list` doesn't have these methods.

#### **Query Descriptor Pattern**
- **Problem**: `Query` dataclass was patched as a class attribute, meaning all NodeSet instances shared the same `Query` object with default `order_by: ["pk"]`.
- **Solution**: Changed `Query` to a descriptor (`_QueryDescriptor`) that returns a per-instance `Query` object, and changed default `order_by` to empty list.
- **Why necessary**: Prevents default `pk` ordering from interfering with our translation logic.

#### **Q Filters Parsing Issue (Monkey-Patch Fix)**
- **Problem**: NeoModel's `_parse_q_filters` method has a bug where `isinstance(child, QBase)` returns `False` for Q objects that are nested as children in `q_filters`. This occurs when:
  - `filter()` is called, which does: `self.q_filters = Q(self.q_filters & Q(...))` (wraps in another Q)
  - Q objects are combined using `&` operator, creating nested Q structures
  - The parser tries to subscript Q objects as tuples (`child[0]`, `child[1]`), causing `"'Q' object is not subscriptable"` errors
- **Root Cause**: The `isinstance(child, QBase)` check in `_parse_q_filters` (line 896 in `neomodel/sync_/match.py`) fails to recognize Q objects as QBase instances, even though `Q` inherits from `QBase`. This may be due to import/class hierarchy issues or how Q objects are created when wrapped.
- **Solution**: Monkey-patch `QueryBuilder._parse_q_filters` with enhanced Q object detection:
  1. **Multiple detection methods**: Uses `isinstance(child, QBase)`, `isinstance(child, Q)`, and `type(child).__name__ == 'Q'` as fallback
  2. **Error handling**: If subscripting fails, checks if child has Q-like attributes (`children`, `connector`) and handles it as a Q object
  3. **Recursive calls**: Uses `self._parse_q_filters` (the patched version) for recursive calls to ensure all nested levels are handled
- **Implementation**: Applied on module import in `admin.py` (lines 16-78) to ensure it's active before any QueryBuilder instances are created
- **Why necessary**: Without this patch, any `q_filters` structure with nested Q objects (from `filter()` or `&` operations) will cause parsing errors. The patch ensures Q objects are always recognized and processed correctly, regardless of whether `isinstance()` works properly.
- **Note**: This is a workaround for a NeoModel bug. Ideally, NeoModel should fix `_parse_q_filters` to properly recognize Q objects, but the monkey-patch ensures compatibility in the meantime.

### **Questions to Validate:**
1. Is `Query` dataclass actually used anywhere? (grep for `query.order_by` or `query.select_related`)
2. Can error handling in `get_changelist()` and `changelist_view()` be simplified or removed?
3. Are management commands actually used, or can users call NeoModel functions directly?
4. **For `DjangoNeoModelAdmin` overrides**: Could these be eliminated by fixing incompatibilities at the NodeSet/DjangoNode level instead?

