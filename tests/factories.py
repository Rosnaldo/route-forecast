"""Factory Boy: build valid model instances with sensible defaults, override
only what a test cares about: UserFactory(is_staff=True)."""

import factory
from factory.django import DjangoModelFactory

from apps.users.models import User


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    password = factory.PostGenerationMethodCall("set_password", "pass12345!")

    @factory.post_generation
    def _save(obj, create, extracted, **kwargs):
        if create:
            obj.save()
