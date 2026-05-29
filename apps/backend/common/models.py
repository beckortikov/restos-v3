from django.db import models


class IdempotencyRecord(models.Model):
    key = models.CharField(max_length=128, unique=True, db_index=True)
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=255)
    user_id = models.BigIntegerField(null=True, blank=True)
    response_status = models.PositiveSmallIntegerField()
    response_body = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Idempotency record"
        verbose_name_plural = "Idempotency records"
        indexes = [models.Index(fields=["created_at"])]

    def __str__(self) -> str:
        return f"{self.method} {self.path} [{self.key[:8]}…]"
