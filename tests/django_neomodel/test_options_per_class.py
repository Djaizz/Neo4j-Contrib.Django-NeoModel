"""Django's Options are per class: a subclass defined or reached after its
parent's Options were built gets its own, never the parent's through the
MRO — ``Model._meta`` is the metaclass's per-class descriptor, ``node._meta``
reaches the same object from an instance."""

from neomodel import StringProperty

from django_neomodel import DjangoNode


class OptionsPerClassParent(DjangoNode):
    __label__ = "OptionsPerClassParent"
    name = StringProperty()

    class Meta:
        app_label = "someapp"
        verbose_name = "parent"


def test_a_subclass_reached_after_its_parent_builds_its_own_options():
    parent_options = OptionsPerClassParent._meta  # the parent first: cached on it alone

    class OptionsPerClassChild(OptionsPerClassParent):
        __label__ = "OptionsPerClassChild"

        class Meta(OptionsPerClassParent.Meta):
            verbose_name = "child"

    child_options = OptionsPerClassChild._meta
    assert child_options is not parent_options
    assert child_options.model is OptionsPerClassChild
    assert child_options.object_name == "OptionsPerClassChild"
    assert child_options.verbose_name == "child"
    # The parent is untouched by the subclass.
    assert OptionsPerClassParent._meta is parent_options
    assert parent_options.verbose_name == "parent"


def test_options_are_cached_per_class_and_reachable_from_an_instance():
    options = OptionsPerClassParent._meta
    assert OptionsPerClassParent._meta is options
    assert OptionsPerClassParent(name="n")._meta is options


def test_deleting_the_cache_rebuilds_on_the_next_access():
    before = OptionsPerClassParent._meta
    del OptionsPerClassParent._meta
    after = OptionsPerClassParent._meta
    assert after is not before
    assert after.object_name == before.object_name == "OptionsPerClassParent"
