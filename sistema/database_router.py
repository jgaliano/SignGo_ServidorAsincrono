class DatabaseRouter:
    """
    Router para dirigir operaciones a los modelos réplica hacia la base de datos signgo.
    """
    
    def db_for_read(self, model, **hints):
        if model._meta.app_label == 'signbox_replicas':
            return 'signgo'
        return 'default'
    
    def db_for_write(self, model, **hints):
        if model._meta.app_label == 'signbox_replicas':
            return 'signgo'
        return 'default'
    
    def allow_relation(self, obj1, obj2, **hints):
        return True  # O implementa lógica más restrictiva si es necesario
    
    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # Crucial: evita que Django intente migrar los modelos réplica
        if app_label == 'signbox_replicas':
            return False
        return True