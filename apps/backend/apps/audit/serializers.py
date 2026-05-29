from rest_framework import serializers

from .models import AuditAction, AuditEntry


class AuditEntrySerializer(serializers.ModelSerializer):
    user_username = serializers.CharField(
        source="user.username", read_only=True, default=None
    )
    action_label = serializers.SerializerMethodField()

    class Meta:
        model = AuditEntry
        fields = [
            "id", "user", "user_username", "user_full_name",
            "action", "action_label",
            "target_type", "target_id",
            "payload", "ip_address", "created_at",
        ]

    def get_action_label(self, obj) -> str:
        return dict(AuditAction.choices).get(obj.action, obj.action)
