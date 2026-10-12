from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base: no table of its own, its fields are copied into children."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
