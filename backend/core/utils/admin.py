class ReadOnlyAdminMixin:
    """Запрещает создание, изменение и удаление в админке."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
