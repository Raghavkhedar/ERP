class ReadOnly:
    """Admin for records the app's own pages manage (version checks, history): look
    but don't touch."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
