# Django-NeoModel Key Affordances and Interfaces Survey

This document enumerates all key affordances and interfaces implemented in Django-NeoModel, along with justifications for their necessity.

---

## Module: `__init__.py`

### 1. **`DjangoField` class** (lines 38-161)
- **Purpose**: Wraps NeoModel `Property` objects to mimic Django `Field` API
- **Justification**: Django Admin and forms expect Django `Field` objects with attributes like `name`, `verbose_name`, `formfield()`, `has_default()`, etc. NeoModel `Property` objects don't have this interface.
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

### 4. **`DjangoNode` class** (lines 187-314)
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

### 5. **`classproperty` decorator** (lines 26-34)
- **Purpose**: Creates class-level properties (like `_meta`)
- **Justification**: `_meta` needs to be a class property, not an instance property
- **Necessity**: ✅ **Required** for `_meta` implementation

---

## Module: `admin.py`

### 1. **`DjangoNeoModelAdmin` class** (lines 22-236)
- **Purpose**: Base `ModelAdmin` for NeoModel nodes
- **Justification**: Django Admin needs customizations to work with NeoModel

**Key methods:**

#### **Permission methods** (lines 35-65)
- `has_add_permission()`, `has_change_permission()`, `has_delete_permission()`, `has_view_permission()`, `has_view_or_change_permission()`
- **Purpose**: Bypass Django's permission system (all return `True`)
- **Justification**: NeoModel doesn't integrate with Django's auth system
- **Necessity**: ✅ **Required** for Django Admin to display pages

#### **`get_queryset()` method** (lines 67-94)
- **Purpose**: Returns NodeSet from `model.objects.all()` with error handling
- **Justification**: Django Admin expects a queryset; converts NeoModel NodeSet
- **Necessity**: ✅ **Required** for Django Admin changelist

#### **`get_object()` method** (lines 96-127)
- **Purpose**: Retrieves single object by primary key
- **Justification**: Django Admin's default expects Django ORM queryset `.get()`. NeoModel uses custom primary keys (not `id`).
- **Necessity**: ✅ **Required** for Django Admin detail/change views

#### **`get_search_results()` method** (lines 129-152)
- **Purpose**: Implements search using NeoModel's `Q` objects
- **Justification**: Django Admin's default uses Django ORM `Q` objects. NeoModel has its own `Q` objects.
- **Necessity**: ✅ **Required** for Django Admin search functionality

#### **`get_changelist()` method** (lines 154-180)
- **Purpose**: Error handling wrapper for ChangeList creation
- **Justification**: Better error visibility during debugging
- **Necessity**: ⚠️ **Helpful for debugging**, not strictly required

#### **`changelist_view()` method** (lines 182-236)
- **Purpose**: Error handling wrapper that returns HTML error page
- **Justification**: Better error visibility during debugging
- **Necessity**: ⚠️ **Helpful for debugging**, not strictly required

---

## Module: `dev.py`

### 1. **Monkey-patches** (lines 15-32)
- **Purpose**: Fixes compatibility issues between Django and NeoModel

**Patches:**

#### **`DjangoField.empty_values`** (lines 17-18)
- **Purpose**: Adds `empty_values` attribute expected by Django's `display_for_field()`
- **Justification**: Django Admin calls `display_for_field()` which expects `field.empty_values`
- **Necessity**: ✅ **Required** for Django Admin field display

#### **`DjangoNode.serializable_value()`** (lines 22-32)
- **Purpose**: Handles `None` field names (Django Admin sometimes passes `None`)
- **Justification**: Django Admin sometimes calls `serializable_value(None)`, which causes `TypeError`
- **Necessity**: ✅ **Required** to prevent crashes in Django Admin

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

### **Core Requirements (Cannot be Removed):**
1. ✅ `DjangoField` - Required for Django Admin/forms
2. ✅ `DjangoNode` with `_meta`, `full_clean()`, `validate_unique()`, `validate_constraints()` - Required for Django Admin/forms
3. ✅ `_ObjectsDescriptor` / `.objects` - Required for Django-like API
4. ✅ `DjangoNeoModelAdmin` permission methods - Required for Django Admin
5. ✅ `DjangoNeoModelAdmin.get_queryset()` - Required for Django Admin
6. ✅ `DjangoNeoModelAdmin.get_object()` - Required for Django Admin detail views
7. ✅ `DjangoNeoModelAdmin.get_search_results()` - Required for Django Admin search
8. ✅ Monkey-patches in `dev.py` - Required to prevent crashes
9. ✅ `NeomodelConfig` - Required for NeoModel configuration in Django

### **Potentially Removable (Debugging/Convenience):**
1. ⚠️ `Query` dataclass - May not be used if Django Admin doesn't need it
2. ⚠️ `DjangoNeoModelAdmin.get_changelist()` - Debugging helper
3. ⚠️ `DjangoNeoModelAdmin.changelist_view()` - Debugging helper
4. ⚠️ Management commands - Convenience features

### **Questions to Validate:**
1. Is `Query` dataclass actually used anywhere? (grep for `query.order_by` or `query.select_related`)
2. Can error handling in `get_changelist()` and `changelist_view()` be simplified or removed?
3. Are management commands actually used, or can users call NeoModel functions directly?

